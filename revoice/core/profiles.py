"""Build per-register style profiles + exemplar banks from the index. v0.

Exemplars: polished docs only, longest-first (length as a crude quality proxy for now).
Profile: LLM distills the register's voice from sampled excerpts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from revoice.core.ingest import extract_text
from revoice.core.voicepack import VoicePack
from revoice.providers.base import Provider

PROFILE_SYSTEM = """BUILD_PROFILE
You are distilling the writing voice of author "{voice}" in their "{register}" register,
from the excerpts provided. Describe how THIS author writes — specific, not generic.

Respond with JSON:
{{"voice_summary": "2-3 sentences on the overall voice",
  "sentence_rhythm": "typical lengths, variation, pacing",
  "vocabulary": "word choices, technicality, favorite constructions",
  "habits": "distinctive tics: punctuation, openings, transitions, humor",
  "never_does": "things this author avoids that generic/AI writing does"}}"""

MAX_EXEMPLARS = 12
EXCERPT_CHARS = 1500
PROFILE_SAMPLE_DOCS = 8


def build_profiles(pack: VoicePack, provider: Provider, progress=None) -> dict:
    index = pack.read_index()
    by_register: dict[str, list[dict]] = {}
    for e in index.values():
        by_register.setdefault(e["register"], []).append(e)

    pack.profiles_dir.mkdir(parents=True, exist_ok=True)
    pack.exemplars_dir.mkdir(parents=True, exist_ok=True)
    built = {}

    for register, entries in by_register.items():
        polished = [e for e in entries if e["polish"] == "polished"] or entries
        polished.sort(key=lambda e: -e["chars"])

        # exemplar bank
        exemplars = []
        for e in polished[:MAX_EXEMPLARS]:
            text = extract_text(pack.training_dir / e["path"])
            if not text:
                continue
            exemplars.append(
                {"path": e["path"], "domains": e["domains"], "excerpt": text[:EXCERPT_CHARS]}
            )
        (pack.exemplars_dir / f"{register}.json").write_text(
            json.dumps(exemplars, ensure_ascii=False, indent=2)
        )

        # profile
        sample = "\n\n---EXCERPT---\n\n".join(x["excerpt"] for x in exemplars[:PROFILE_SAMPLE_DOCS])
        try:
            profile = provider.complete_json(
                PROFILE_SYSTEM.format(voice=pack.name, register=register), sample
            )
        except Exception as e:  # noqa: BLE001
            if progress:
                progress(register, f"profile ERROR: {e}")
            continue
        profile["register"] = register
        profile["doc_count"] = len(entries)
        profile["built_at"] = datetime.now(timezone.utc).isoformat()
        (pack.profiles_dir / f"{register}.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2)
        )
        built[register] = len(exemplars)
        if progress:
            progress(register, f"{len(entries)} docs, {len(exemplars)} exemplars")

    readiness = "prompts_ready" if built else "not_ready"
    pack.update_manifest(registers=sorted(by_register), readiness=readiness)
    return built
