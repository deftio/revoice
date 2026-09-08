"""Pass 0 — original_text_eval, 100% deterministic. No LLM, ever.

Reads the whole document and emits a machine-usable plan: what this document is
(statistically), what arrives in which register, where the seams are for chunking,
and per-segment cautions/treatment. Pure functions of the text (+ optional voice
baselines), so it runs instantly, identically, and with nothing configured —
a drop-in library call.

    from revoice.core.preflight import build_plan
    plan = build_plan(text)                      # no voice needed
    plan = build_plan(text, pack, "technical")   # adds register attribution
"""

from __future__ import annotations

import re

from revoice.core.segments import analyze_blend, classify_segment
from revoice.voicemetric.features import fingerprint, tokenize

# ---- deterministic detectors ----

MATH_RX = re.compile(
    r"[=+^]|\\[a-zA-Z]+|\$[^$]+\$|[±×÷√∑∏∫≈≤≥]"
    r"|\b\d+(?:\.\d+)?\s*(?:Hz|kHz|MHz|V|mV|A|mA|Ω|ohm|dB|ms|us|ns|°C)\b"
)
DIALOG_RX = re.compile(r'["“][^"”]{2,120}["”]')
CITE_RX = re.compile(r"\[\d{1,3}\]|\b\w+(?: et al\.?| and \w+)?,? \(?\d{4}\)?[,.);]|\bet al\.|\bibid\.|\bop\. cit\.")
URL_RX = re.compile(r"https?://\S+|www\.\S+")
HEADING_RX = re.compile(r"^#{1,6}\s|^={3,}\s*$|^-{3,}\s*$", re.MULTILINE)

TARGET_CHUNK_CHARS = 6000  # generation chunk size; seams snap to structure


def _density(rx: re.Pattern, text: str, per_chars: int = 1000) -> float:
    return round(len(rx.findall(text)) / max(len(text) / per_chars, 0.001), 2)


def _doc_kind(blend: dict, fp: dict, text: str) -> str:
    """Crude but deterministic document-type call from measured signals."""
    b = blend["blend"]
    if b.get("code", 0) + b.get("numeric", 0) > 0.5:
        return "data-or-code-heavy"
    if _density(CITE_RX, text) > 0.3:
        return "academic-paper-like"
    if b.get("narrative", 0) > 0.6 and _density(DIALOG_RX, text) > 0.4:
        return "fiction-dialogue"
    if b.get("narrative", 0) > 0.6:
        return "narrative-prose"
    if b.get("list", 0) > 0.3:
        return "notes-or-outline"
    if _density(MATH_RX, text) > 1.0:
        return "technical-quantitative"
    return "expository-prose"


def _segments_plan(text: str, pack=None, target_register: str | None = None) -> list[dict]:
    """Per-segment (blank-line paragraphs grouped by type) treatment decisions."""
    from revoice.core.metrics import load_baselines, load_calibration, score_text, span_floor

    baselines = load_baselines(pack) if pack else {}
    calib = load_calibration(pack) if pack else {}
    baseline = baselines.get(target_register) if target_register else None

    out = []
    pos = 0
    for para in re.split(r"\n\s*\n", text):
        if not para.strip():
            pos += len(para) + 2
            continue
        kind = classify_segment(para)
        seg = {"offset": pos, "chars": len(para), "type": kind}
        cautions = []
        if _density(MATH_RX, para) > 2.0:
            cautions.append("math-dense: preserve all notation and units verbatim")
        if URL_RX.search(para):
            cautions.append("contains URLs: preserve exactly")
        if CITE_RX.search(para):
            cautions.append("contains citations: preserve exactly")
        if _density(DIALOG_RX, para) > 1.0:
            cautions.append("dialogue-heavy: preserve quoted speech content")
        if kind in ("code", "numeric"):
            seg["treatment"] = "protect"
        elif kind in ("list", "fragment") and len(para) < 120:
            seg["treatment"] = "cleanup-only"
        else:
            seg["treatment"] = "revoice"
            n_words = len(tokenize(para)[0])
            if baseline and n_words >= 25:
                comp = score_text(para, baseline)["composite"]
                seg["register_score"] = comp
                # length-matched band, same as pipeline attribution
                floor = span_floor(calib, target_register, n_words)
                if floor is not None:
                    seg["register_floor"] = round(floor, 1)
                    if comp >= floor:
                        seg["treatment"] = "pass-through (on-target)"
        if cautions:
            seg["cautions"] = cautions
        out.append(seg)
        pos += len(para) + 2
    return out


def _chunk_seams(text: str) -> list[int]:
    """Character offsets where large-doc generation should split. Deterministic:
    prefer heading positions, else paragraph boundaries nearest the target size."""
    if len(text) <= TARGET_CHUNK_CHARS:
        return []
    headings = [m.start() for m in HEADING_RX.finditer(text)]
    paras = [m.start() for m in re.finditer(r"\n\s*\n", text)]
    seams, cursor = [], TARGET_CHUNK_CHARS
    while cursor < len(text):
        window = [h for h in headings if cursor - 2000 <= h <= cursor + 2000]
        cands = window or [p for p in paras if cursor - 1500 <= p <= cursor + 1500]
        seam = min(cands, key=lambda x: abs(x - cursor)) if cands else cursor
        seams.append(seam)
        cursor = seam + TARGET_CHUNK_CHARS
    return seams


def build_plan(text: str, pack=None, target_register: str | None = None) -> dict:
    """The deterministic original_text_eval. Same input -> same plan, no LLM."""
    fp = fingerprint(text)
    blend = analyze_blend(text)
    segs = _segments_plan(text, pack, target_register)
    treatments = {}
    for s in segs:
        treatments[s["treatment"]] = treatments.get(s["treatment"], 0) + 1
    plan = {
        "doc_kind": _doc_kind(blend, fp, text),
        "chars": len(text),
        "words": fp["words"],
        "blend": blend["blend"],
        "verdict": blend["verdict"],
        "style_heterogeneity": blend["style_heterogeneity"],
        "densities": {
            "math": _density(MATH_RX, text),
            "dialogue": _density(DIALOG_RX, text),
            "citations": _density(CITE_RX, text),
            "urls": _density(URL_RX, text),
        },
        "chunking": {"needed": len(text) > TARGET_CHUNK_CHARS,
                     "target_chars": TARGET_CHUNK_CHARS,
                     "seams": _chunk_seams(text)},
        "treatment_summary": treatments,
        "segments": segs,
    }
    if target_register:
        plan["target_register"] = target_register
    return plan
