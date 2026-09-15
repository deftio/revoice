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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from revoice.voicemetric.baseline import baseline_from_texts, score_text  # noqa: E402

ROOT = Path(__file__).parent.parent
OUT = ROOT / "pages" / "demo" / "voices.json"
POP_OUT = ROOT / "pages" / "demo" / "population.json"
VERSION_OUT = ROOT / "pages" / "version.js"
CONSTANTS_OUT = ROOT / "pages" / "engine-constants.js"

# Where the browser's voice-space population comes from. The benchmark corpus if it has
# been fetched, otherwise the bundled example voices — a narrower reference, but the
# alternative is z-scoring a reader's prose against nothing at all.
POPULATION_SOURCES = (ROOT / "bench-corpus", ROOT / "examples" / "voices")

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


# `vocab` is dropped from the shipped baselines on purpose. It is weighted 0.0 in the
# voice score by construction (see VOICE_COMPONENTS), so `score_text` returning vocab=0.0
# against an absent centroid leaves the composite bit-identical — while `df` alone would
# be most of the file, since it carries every content term in the corpus.
DROP_FROM_SHIPPED = ("df", "tfidf_centroid")


def build(voice_dir: Path) -> dict:
    """Per-register baselines for the demo page, built by the REAL engine.

    This function used to carry its own `_aggregate` and `_demo_score` — a third
    implementation of the composite alongside the Python engine and the browser port,
    running weights of 0.2/0.6/0.1/0.1 under a docstring that said "keep the weights in
    sync". They were not in sync: the fitted values are 0.318/0.181/0.0/0.332 plus four
    components that implementation did not have at all. Nothing enforced the comment,
    so the comment lost.

    Now there is one implementation. `baseline_from_texts` and `score_text` are the same
    functions `revoice learn` and `revoice stats` call, and pages/voicemetric.js is a
    parity-tested port of exactly them.
    """
    groups: dict[str, list[str]] = {}
    for f in sorted((voice_dir / "training-data").glob("*.md")):
        prefix = f.name.split("-")[0]
        reg = PREFIX_REGISTER.get(prefix)
        if reg:
            groups.setdefault(reg, []).extend(_windows(f.read_text()))

    registers = {reg: baseline_from_texts(texts) for reg, texts in groups.items()}

    # Self-calibration, LEAVE-ONE-OUT. Scoring a window against a baseline it helped
    # build is contaminated: the window pulls the mean toward itself, so the band lands
    # too high and too tight, and every candidate then scores lower than it should.
    for reg, texts in groups.items():
        selfs = []
        for i, t in enumerate(texts):
            rest = texts[:i] + texts[i + 1:]
            if len(rest) < 2:
                continue
            selfs.append(score_text(t, baseline_from_texts(rest))["composite"])
        if not selfs:  # too few windows to hold one out
            selfs = [score_text(t, registers[reg])["composite"] for t in texts]
        m, s = _mean_std(selfs)
        registers[reg]["self"] = [round(m, 1), round(max(s, 1.0), 1)]

    for base in registers.values():
        for k in DROP_FROM_SHIPPED:
            base.pop(k, None)
    return registers


def export_population(quiet: bool = False) -> dict:
    """Export the voice-space reference population for the browser.

    Seventeen axes x (mean, sd) is ~34 numbers, so the page can z-score a reader's text
    against real English prose instead of against itself. Without this the browser would
    have to treat whatever was pasted in as its own definition of "typical", which makes
    every coordinate near zero and the chart meaningless.
    """
    from revoice.voicemetric import version as vm_version
    from revoice.voicemetric.bench import load_corpus
    from revoice.voicemetric.space import AXIS_NAMES, Population

    for root in POPULATION_SOURCES:
        if not root.is_dir():
            continue
        docs = load_corpus(root)
        if len(docs) < 20:
            continue
        pop = Population.fit([d.text for d in docs])
        payload = {"n": pop.n, "source": root.name, "voicemetric": vm_version(),
                   "axes": list(AXIS_NAMES),
                   "stats": {a: [round(pop.stats[a][0], 6), round(pop.stats[a][1], 6)]
                             for a in AXIS_NAMES}}
        POP_OUT.parent.mkdir(parents=True, exist_ok=True)
        POP_OUT.write_text(json.dumps(payload, separators=(",", ":")))
        if not quiet:
            print(f"wrote {POP_OUT} ({pop.n} documents from {root.name})")
        return payload
    print(f"skipped {POP_OUT}: no corpus with >=20 documents found", file=sys.stderr)
    return {}


def export_versions(quiet: bool = False) -> None:
    """A tiny synchronous JS file, so the page can print its version without a fetch."""
    import revoice
    from revoice import rubric
    from revoice.voicemetric import signature
    from revoice.voicemetric import version as vm_version

    payload = {"revoice": revoice.__version__, "voicemetric": vm_version(),
               "voicemetric_signature": signature(), "rubric": rubric.version()}
    VERSION_OUT.write_text(
        "/* generated by scripts/export_demo_baselines.py — do not edit */\n"
        f"var REVOICE_VERSION = {json.dumps(payload, indent=2)};\n")
    if not quiet:
        print(f"wrote {VERSION_OUT} (revoice {payload['revoice']})")


def export_constants(quiet: bool = False) -> None:
    """Emit every shared constant as JS, so the two implementations cannot disagree.

    The engine exists twice — once in Python, once in JavaScript, because the compare
    page runs off GitHub Pages with no server to ask. Two implementations of anything
    drift; the question is only what you do about it. Here the split is deliberate:

      DATA      lives in Python and is generated into this file. Word lists, histogram
                bins, component weights, axis names, punctuation sets. These are the
                parts that drift silently and cost the most when they do — the page
                spent months scoring with `ngram` at 0.6 while the fitted weight was
                0.181, because the number had been typed into the JS by hand and the
                Python was refitted three times afterwards.
      ALGORITHM lives in both, and is held together by tests/test_pages_parity.py,
                which runs the real JavaScript under node against the real Python on
                shared fixtures every time the suite runs.

    A constant that is generated cannot be edited into disagreement. An algorithm that
    is tested cannot drift without a failure. Nothing else is load-bearing.
    """
    from revoice.voicemetric.baseline import (
        COMPONENTS,
        PUNCT_RATIO_SCALARS,
        PUNCTS,
        RICHNESS_SCALARS,
        SCALARS,
        STRUCTURE_SCALARS,
        SYNTAX_SCALARS,
        VOICE_COMPONENTS,
        WEIGHTS,
    )
    from revoice.voicemetric.features import (
        ARTICLES,
        CONJUNCTIONS,
        FUNCTION_WORDS,
        OPENER_CLASSES,
        PARA_HIST_BINS,
        PREPOSITIONS,
        PRONOUNS,
        SENT_HIST_BINS,
        STOP,
        SUBORDINATORS,
        TOP_CHAR_NGRAMS,
        TOP_WORD_BIGRAMS,
        WORD_HIST_BINS,
    )
    from revoice.voicemetric.features import (
        CHAR_NGRAM_N as NGRAM_N,
    )
    from revoice.voicemetric.space import AXES, FIRST_PERSON, MIN_SPREAD, SECOND_PERSON
    from revoice.voicemetric.transfer import HEDGES, MEANING_FLOOR, NEGATIONS

    payload = {
        "FUNCTION_WORDS": list(FUNCTION_WORDS),
        # sets are emitted sorted: Python set iteration order is not stable across
        # runs, and an unstable generated file would churn the diff every regeneration
        "ARTICLES": sorted(ARTICLES),
        "PRONOUNS": sorted(PRONOUNS),
        "CONJUNCTIONS": sorted(CONJUNCTIONS),
        "SUBORDINATORS": sorted(SUBORDINATORS),
        "PREPOSITIONS": sorted(PREPOSITIONS),
        "OPENER_CLASSES": list(OPENER_CLASSES),
        "STOP": sorted(STOP),
        "SENT_HIST_BINS": list(SENT_HIST_BINS),
        "WORD_HIST_BINS": list(WORD_HIST_BINS),
        "PARA_HIST_BINS": list(PARA_HIST_BINS),
        "PUNCTS": list(PUNCTS),
        "COMPONENTS": list(COMPONENTS),
        "VOICE_COMPONENTS": list(VOICE_COMPONENTS),
        "WEIGHTS": dict(WEIGHTS),
        "RICHNESS_SCALARS": list(RICHNESS_SCALARS),
        "SYNTAX_SCALARS": list(SYNTAX_SCALARS),
        "STRUCTURE_SCALARS": list(STRUCTURE_SCALARS),
        "PUNCT_RATIO_SCALARS": list(PUNCT_RATIO_SCALARS),
        "SCALARS": list(SCALARS),
        "CHAR_NGRAM_N": NGRAM_N,
        "TOP_CHAR_NGRAMS": TOP_CHAR_NGRAMS,
        "TOP_WORD_BIGRAMS": TOP_WORD_BIGRAMS,
        "AXES": [{"name": a.name, "low": a.low, "high": a.high, "family": a.family}
                 for a in AXES],
        "MIN_SPREAD": MIN_SPREAD,
        "FIRST_PERSON": sorted(FIRST_PERSON),
        "SECOND_PERSON": sorted(SECOND_PERSON),
        "NEGATIONS": sorted(NEGATIONS),
        "HEDGES": sorted(HEDGES),
        "MEANING_FLOOR": MEANING_FLOOR,
    }
    CONSTANTS_OUT.write_text(
        "/* generated by scripts/export_demo_baselines.py — do not edit.\n"
        "   Every shared constant between the Python engine and its browser port. The\n"
        "   ALGORITHMS live in both and are held together by tests/test_pages_parity.py;\n"
        "   the DATA lives in Python and is generated here, because hand-copied data is\n"
        "   what actually drifts. The page scored with ngram weighted 0.6 for months\n"
        "   while the fitted value was 0.181, for exactly that reason. */\n"
        f"var VM_CONST = {json.dumps(payload, indent=2, ensure_ascii=False)};\n")
    if not quiet:
        print(f"wrote {CONSTANTS_OUT} ({CONSTANTS_OUT.stat().st_size/1024:.1f} KB, "
              f"{len(payload)} constant groups)")


def _population_source_available() -> tuple[bool, str, str]:
    """Can this checkout reproduce the committed population? (ok, committed, available)

    `bench-corpus/` is fetched data and gitignored, so a fresh clone does not have it and
    `export_population` silently falls back to `examples/voices` — 4 voices instead of
    1,594 documents. The generated file records which source produced it, so the mismatch
    is detectable, and it must be detected: without this, `--check` reports "stale" in
    any checkout without the corpus, and following its advice would regenerate the
    population from the fallback and commit a materially different file.

    Reporting "I cannot verify this here" is the honest answer. Reporting "stale" is an
    instruction to break it.
    """
    committed = ""
    if POP_OUT.is_file():
        try:
            committed = json.loads(POP_OUT.read_text()).get("source", "")
        except (json.JSONDecodeError, OSError):
            committed = ""
    available = ""
    for root in POPULATION_SOURCES:
        if root.is_dir():
            available = root.name
            break
    return (not committed or not available or committed == available), committed, available


def check() -> int:
    """Verify the generated files are current, writing nothing.

    The release script uses this. Regenerating during a release would mean the release
    authors code, and then what ships is not what was reviewed and tested — so release
    checks, and the developer regenerates as part of normal work.
    """
    ok_source, committed, available = _population_source_available()
    if not ok_source:
        print(f"cannot verify the generated files here: pages/demo/population.json was "
              f"built from '{committed}', but this checkout only has '{available}'.",
              file=sys.stderr)
        print(f"Regenerating would REPLACE it with a smaller, different population.\n"
              f"Fetch the corpus first:\n"
              f"    python scripts/fetch_bench_corpus.py\n"
              f"or run this check on a checkout that has {committed}/.", file=sys.stderr)
        return 2
    before = {f: f.read_bytes() if f.is_file() else None for f in (OUT, POP_OUT, VERSION_OUT, CONSTANTS_OUT)}
    main(quiet=True)
    stale = [f.name for f, prior in before.items() if f.read_bytes() != prior]
    for f, prior in before.items():          # leave the tree exactly as found
        if prior is None:
            f.unlink(missing_ok=True)
        else:
            f.write_bytes(prior)
    if stale:
        print("stale generated files: " + ", ".join(stale), file=sys.stderr)
        print("regenerate with: python scripts/export_demo_baselines.py", file=sys.stderr)
        return 1
    print("generated files are current")
    return 0


def main(quiet: bool = False):
    voices = {}
    for vdir in sorted((ROOT / "examples" / "voices").iterdir()):
        if (vdir / "training-data").is_dir():
            voices[vdir.name] = build(vdir)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(voices, ensure_ascii=False, separators=(",", ":")))
    size = OUT.stat().st_size
    if not quiet:
        print(f"wrote {OUT} ({size/1024:.0f} KB): " +
              ", ".join(f"{v}[{'/'.join(r)}]" for v, r in
                        ((k, list(vv)) for k, vv in voices.items())))
    export_population(quiet)
    export_versions(quiet)
    export_constants(quiet)


if __name__ == "__main__":
    raise SystemExit(check() if "--check" in sys.argv else main())
