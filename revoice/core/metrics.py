"""Voice-pack-aware wrappers around `revoice.voicemetric`.

The measurement itself lives in `revoice/voicemetric/`, which knows nothing about voice
packs, file formats or where anything is stored. This file is the seam: it reads a
pack's corpus, hands texts to the measurement code, and writes the results back into
`params/`. Same division of labour as `revoice/rubric/` and `core/rubrics.py`.

Everything the rest of revoice imported from here still resolves, so callers need not
care which side of the seam a name lives on.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import revoice.voicemetric as voicemetric
from revoice.core.ingest import extract_text
from revoice.core.voicepack import VoicePack

# re-exported so the rest of revoice keeps one import site for measurement
from revoice.voicemetric.baseline import (  # noqa: F401
    COMPONENTS,
    LOO_MAX_DOCS,
    MIN_WORDS_RELIABLE,
    PUNCT_RATIO_SCALARS,
    PUNCTS,
    RICHNESS_SCALARS,
    SCALARS,
    SPAN_BUCKETS,
    SPAN_SAMPLES_PER_BUCKET,
    STRUCTURE_SCALARS,
    SYNTAX_SCALARS,
    VOICE_COMPONENTS,
    WEIGHTS,
    _bucket_for,
    _mean_std,
    baseline_from_texts,
    calibration_from_texts,
    score_text,
    span_floor,
)


def _texts_by_register(pack: VoicePack) -> dict[str, list[str]]:
    """Read the pack's corpus once, grouped by register. Unreadable entries are skipped:
    the index is a cache keyed by path, so a deleted document is a normal occurrence."""
    out: dict[str, list[str]] = {}
    for e in pack.read_index().values():
        text = extract_text(pack.training_dir / e["path"])
        if text:
            out.setdefault(e["register"], []).append(text)
    return out


def build_baselines(pack: VoicePack, progress=None) -> dict:
    """Aggregate per-register baselines over the pack's indexed corpus, and calibrate."""
    by_register = _texts_by_register(pack)

    baselines = {}
    for register, texts in by_register.items():
        baselines[register] = baseline_from_texts(texts)
        if progress:
            progress(register, f"baseline from {len(texts)} docs")

    # Stamp the engine into both artefacts. A baseline outlives the code that made it,
    # and refitting the composite weights silently changes every score computed against
    # an old one — `signature` is what turns that from a mystery into a diff.
    stamp = {"_engine": {**voicemetric.describe(),
                         "built": datetime.now(timezone.utc).isoformat(timespec="seconds")}}
    (pack.params_dir / "baselines.json").write_text(json.dumps({**stamp, **baselines}))
    calib = calibration_from_texts(baselines, by_register, progress)
    (pack.params_dir / "calibration.json").write_text(json.dumps({**stamp, **calib}, indent=2))
    pack.update_manifest(voicemetric=voicemetric.describe())
    return baselines


def _load_stamped(path) -> dict:
    """Read a stamped artefact, returning only its registers.

    `_engine` sits alongside the register keys rather than nesting the data a level
    deeper, so every existing reader keeps working; it is stripped here so no caller
    mistakes it for a register named "_engine".
    """
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def load_baselines(pack: VoicePack) -> dict:
    return _load_stamped(pack.params_dir / "baselines.json")


def load_calibration(pack: VoicePack) -> dict:
    return _load_stamped(pack.params_dir / "calibration.json")


def engine_of(pack: VoicePack) -> dict:
    """Which voicemetric build produced this pack's baselines, if it recorded one."""
    p = pack.params_dir / "baselines.json"
    if not p.is_file():
        return {}
    return json.loads(p.read_text()).get("_engine", {})


def score_against_pack(text: str, pack: VoicePack, register: str | None = None) -> dict:
    """Score text against one register of a pack (or all, returning the best + full table)."""
    baselines = load_baselines(pack)
    if not baselines:
        raise RuntimeError(f"no baselines for voice '{pack.name}' — run: revoice learn {pack.name}")
    calib = load_calibration(pack)

    targets = [register] if register else sorted(baselines)
    results = {}
    for reg in targets:
        if reg not in baselines:
            raise RuntimeError(
                f"register '{reg}' not in voice '{pack.name}' (have: {sorted(baselines)})")
        r = score_text(text, baselines[reg])
        r["calibration"] = calib.get(reg, {})
        results[reg] = r
    best = max(results, key=lambda k: results[k]["composite"])
    return {"best_register": best, "results": results}
