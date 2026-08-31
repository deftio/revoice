"""Corpus indexer: classify every training doc on register / polish / domain axes.

Incremental: files are keyed by content hash; unchanged files are skipped on re-run.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from revoice.core.ingest import extract_text, walk_corpus
from revoice.core.stylometry import fingerprint
from revoice.core.voicepack import VoicePack
from revoice.providers.base import Provider

CLASSIFY_SYSTEM = """CLASSIFY_DOC
You are indexing one document from a personal writing corpus for author {voice}.
Classify it on three axes:

- register: the voice/mode of the writing. Use an existing value from this list when it fits,
  otherwise propose a new lowercase snake_case value: {known_registers}
- polish: one of polished | draft | brain_dump
- domains: 1-3 subject domains, lowercase snake_case (e.g. electrical_engineering, economics, cooking)

Also give a one-sentence summary and a confidence 0-1 for the register call.

Respond with JSON: {{"register": ..., "polish": ..., "domains": [...], "summary": ..., "confidence": ...}}"""

DEFAULT_REGISTERS = ["professional", "casual", "fiction", "poetry", "email"]
MAX_CLASSIFY_CHARS = 8000


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def index_corpus(pack: VoicePack, provider: Provider, progress=None) -> dict:
    """Classify new/changed files into index.jsonl. Returns stats."""
    existing = pack.read_index()
    known_registers = sorted(
        set(DEFAULT_REGISTERS) | {e["register"] for e in existing.values() if e.get("register")}
    )
    stats = {"total": 0, "classified": 0, "skipped": 0, "unsupported": 0, "errors": 0}

    for path, rel in walk_corpus(pack.training_dir):
        stats["total"] += 1
        text = extract_text(path)
        if text is None:
            stats["unsupported"] += 1
            continue
        if not text.strip():
            stats["skipped"] += 1
            continue
        h = _hash(text)
        prev = existing.get(rel)
        if prev and prev.get("hash") == h:
            stats["skipped"] += 1
            continue

        sample = text[:MAX_CLASSIFY_CHARS]
        try:
            result = provider.complete_json(
                CLASSIFY_SYSTEM.format(voice=pack.name, known_registers=", ".join(known_registers)),
                sample,
            )
        except Exception as e:  # noqa: BLE001 — one bad doc shouldn't kill the run
            stats["errors"] += 1
            if progress:
                progress(rel, f"ERROR: {e}")
            continue

        entry = {
            "path": rel,
            "hash": h,
            "chars": len(text),
            "register": str(result.get("register", "unknown")).strip().lower(),
            "polish": str(result.get("polish", "unknown")).strip().lower(),
            "domains": [str(d).strip().lower() for d in result.get("domains", [])],
            "summary": result.get("summary", ""),
            "confidence": result.get("confidence", None),
            "fingerprint": fingerprint(text),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        pack.append_index(entry)
        if entry["register"] not in known_registers:
            known_registers.append(entry["register"])
        stats["classified"] += 1
        if progress:
            progress(rel, f"{entry['register']}/{entry['polish']} {entry['domains']}")

    pack.update_manifest(last_indexed=datetime.now(timezone.utc).isoformat(), index_stats=stats)
    return stats
