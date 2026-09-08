"""Export compact per-register baselines from the example voice packs for the
static GitHub Pages demo (docs/demo/voices.json). Deterministic, no LLM:
registers come from training-data filename prefixes (essay-/fiction-/memoir-/science-).

Run:  python scripts/export_demo_baselines.py
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from revoice.voicemetric.features import (  # noqa: E402
    FUNCTION_WORDS,
    char_ngram_profile,
    fingerprint,
    word_bigram_profile,
)

ROOT = Path(__file__).parent.parent
OUT = ROOT / "pages" / "demo" / "voices.json"

PREFIX_REGISTER = {"essay": "essay", "fiction": "fiction",
                   "memoir": "memoir", "science": "science"}
TOP_NGRAMS = 150


def _mean_std(xs):
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / len(xs)
    return m, math.sqrt(v)


def _windows(text: str, target: int = 1200) -> list[str]:
    """Split into ~target-char windows on paragraph boundaries so every register's
    baseline is built from comparably-sized pieces (kills doc-size bias)."""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur, size = [], [], 0
    for p in paras:
        cur.append(p)
        size += len(p)
        if size >= target:
            out.append("\n\n".join(cur))
            cur, size = [], 0
    if cur:
        out.append("\n\n".join(cur))
    return [w for w in out if len(w) > 300]


def _aggregate(texts: list[str]) -> dict:
    """Baseline from a list of windows. Pure aggregation, so leave-one-out
    calibration can rebuild it without duplicating the logic."""
    fps = [fingerprint(t) for t in texts]
    fw = {}
    for w in FUNCTION_WORDS:
        m, s = _mean_std([fp["function_word_freq"].get(w, 0.0) for fp in fps])
        fw[w] = [round(m, 5), round(max(s, 1e-6), 5)]
    n = len(fps)
    hist = [round(sum(fp["sent_len_hist"][i] for fp in fps) / n, 4)
            for i in range(len(fps[0]["sent_len_hist"]))]
    punct = {}
    for p in ",;:—–()!?\"'":
        m, s = _mean_std([fp["punct_per_sentence"].get(p, 0.0) for fp in fps])
        punct[p] = [round(m, 4), round(max(s, 1e-6), 4)]
    cent: Counter = Counter()
    for t in texts:
        for k, v in char_ngram_profile(t).items():
            cent[k] += v / len(texts)
    ngrams = {k: round(v, 6) for k, v in cent.most_common(TOP_NGRAMS)}
    bcent: Counter = Counter()
    for t in texts:
        for k, v in word_bigram_profile(t).items():
            bcent[k] += v / len(texts)
    bigrams = {k: round(v, 6) for k, v in bcent.most_common(TOP_NGRAMS)}
    return {"doc_count": n, "function_words": fw, "sent_len_hist": hist,
            "punct": punct, "char_ngrams": ngrams, "word_bigrams": bigrams}


def build(voice_dir: Path) -> dict:
    groups: dict[str, list[str]] = {}
    for f in sorted((voice_dir / "training-data").glob("*.md")):
        prefix = f.name.split("-")[0]
        reg = PREFIX_REGISTER.get(prefix)
        if reg:
            groups.setdefault(reg, []).extend(_windows(f.read_text()))

    registers = {reg: _aggregate(texts) for reg, texts in groups.items()}

    # Self-calibration, LEAVE-ONE-OUT (mirrors buildBaseline() in pages/stylometry.js).
    # Scoring a window against a baseline it helped build is contaminated: the window
    # pulls the mean toward itself, so the band lands too high and too tight, and every
    # candidate then scores lower than it should against it.
    for reg, texts in groups.items():
        selfs = []
        for i, t in enumerate(texts):
            rest = texts[:i] + texts[i + 1:]
            if len(rest) < 2:
                continue
            selfs.append(_demo_score(t, _aggregate(rest)))
        if not selfs:  # too few windows to hold one out
            selfs = [_demo_score(t, registers[reg]) for t in texts]
        m, s = _mean_std(selfs)
        registers[reg]["self"] = [round(m, 1), round(max(s, 1.0), 1)]
    return registers


def _demo_score(text: str, base: dict) -> float:
    """Python mirror of the JS score() in pages/stylometry.js — keep the weights in sync.

    Weights come from `revoice bench` (topic-controlled): 0.2/0.6/0.1/0.1 scores
    macro AUC 0.687 vs 0.641 for the previous even split.
    """
    fp = fingerprint(text)
    ng = char_ngram_profile(text, top=300)
    zs = []
    for w, (m, s) in base["function_words"].items():
        zs.append(abs(fp["function_word_freq"].get(w, 0.0) - m) / max(s, 0.15 * m + 5e-4))
    delta_sim = math.exp(-(sum(zs) / len(zs)) / 1.5)
    l1 = sum(abs(a - b) for a, b in zip(fp["sent_len_hist"], base["sent_len_hist"], strict=False))
    rhythm = 1 - l1 / 2
    def _cos(a, b):
        dot = sum(v * b.get(k, 0.0) for k, v in a.items())
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    ngram = _cos(ng, base["char_ngrams"])
    if base.get("word_bigrams"):
        ngram = 0.5 * ngram + 0.5 * _cos(word_bigram_profile(text), base["word_bigrams"])
    ps = []
    for p, (m, s) in base["punct"].items():
        ps.append(math.exp(-abs(fp["punct_per_sentence"].get(p, 0.0) - m) / max(s, 0.05)))
    punct = sum(ps) / len(ps)
    return 100 * (0.2 * delta_sim + 0.6 * ngram + 0.1 * rhythm + 0.1 * punct)


def main():
    voices = {}
    for vdir in sorted((ROOT / "examples" / "voices").iterdir()):
        if (vdir / "training-data").is_dir():
            voices[vdir.name] = build(vdir)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(voices, ensure_ascii=False, separators=(",", ":")))
    size = OUT.stat().st_size
    print(f"wrote {OUT} ({size/1024:.0f} KB): " +
          ", ".join(f"{v}[{'/'.join(r)}]" for v, r in
                    ((k, list(vv)) for k, vv in voices.items())))


if __name__ == "__main__":
    main()
