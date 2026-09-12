"""Grading a *rewrite*: did it move toward the target voice, and did it keep the meaning?

Everything else in this package answers "how alike are these two texts?" — an absolute
question, and a hard one. Across 70 authors with same-genre negatives the composite
reaches AUC ~0.69, which is a weak discriminator to hang a product on.

This module asks a different and much easier question:

    Delta_style = D(source, target) - D(rewrite, target)

Did the *same text*, rewritten, move closer to the target voice than it started? Source
and rewrite share their topic, their length, their genre, their era and their content —
every confound that makes absolute scoring weak cancels in the difference. A 0.69-quality
measurement can still be useful on a paired comparison, because the pairing removes
almost everything it was confusing for style.

It is also the question revoice actually has to answer. "This passage scores 43 against
Twain" was never the product question; "this rewrite moved 11 points toward Twain, and
that movement is larger than the noise" is.

The second axis is non-negotiable and deliberately never merged into the first. A rewrite
that nails an author's punctuation habits while quietly changing what a sentence claims
is not a good rewrite, and a single blended number would score it as one. So:

    style      did it move toward the voice        signed, with a confidence interval
    meaning    did the claims survive the rewrite  per family, weakest link wins

`grade()` returns both and refuses to average them.

Portability is a hard constraint, not a nicety: the compare page runs this in a browser
off GitHub Pages, with no server to ask. Everything here is stdlib Python written so it
ports one-to-one to `pages/voicespace.js` — including the bootstrap PRNG, which is a
plain LCG in both so the intervals (and therefore the verdicts) agree exactly rather
than approximately.
"""

from __future__ import annotations

import re
from collections import Counter

from revoice.voicemetric.features import FUNCTION_WORDS
from revoice.voicemetric.space import (
    AXIS_NAMES,
    Population,
    VoiceRegion,
    _percentile,
    axis_similarity,
    windows,
)

# ---------------------------------------------------------------- meaning preservation --

# Lexical retention, not entailment. Stated plainly because the distinction is the whole
# honest limit of this axis: it catches what a rewrite DROPPED or SWAPPED, which is the
# common failure mode (a figure vanishes, a hedge is deleted and a suggestion becomes a
# claim, a name is replaced). It cannot catch a reordering that inverts meaning while
# keeping every token. An embedding or entailment model would; neither runs in a page
# off GitHub Pages, and a lexical floor that ships beats a semantic ceiling that doesn't.

WORD_RX = re.compile(r"[A-Za-z][A-Za-z'-]*")
NUMBER_RX = re.compile(r"\d+(?:[.,]\d+)*%?")

NEGATIONS = {"not", "no", "never", "none", "nothing", "nor", "cannot", "neither",
             "without", "nowhere", "nobody"}
# Dropping a hedge is the classic scientific-prose failure: "the data suggest X" becomes
# "the data show X" and the rewrite has asserted something the source did not.
HEDGES = {"may", "might", "could", "perhaps", "possibly", "likely", "unlikely",
          "suggests", "suggest", "suggested", "appears", "appear", "seems", "seem",
          "probably", "approximately", "roughly", "estimated", "indicate", "indicates",
          "potentially", "generally", "typically", "usually", "apparently", "presumably"}

_FUNCTION_SET = set(FUNCTION_WORDS)
PRESERVATION_FAMILIES = ("numbers", "entities", "negation", "hedges", "content")


def _stem(word: str) -> str:
    """Crude, deterministic suffix stripping so "measured"/"measures" count as one claim.

    Not linguistics — a fixed rule that the JavaScript port reproduces character for
    character. Over-stemming costs a little sensitivity; disagreeing with the browser
    would cost the whole number its meaning.
    """
    w = word.lower()
    if w.endswith("'s"):
        w = w[:-2]
    for suf in ("ing", "ed", "es", "ly", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            break
    # Then a trailing "e", or the rule above splits the same word three ways: "measured"
    # loses "ed" and becomes "measur" while "measure" keeps its "e" and stays whole, so a
    # rewrite that changed the tense would read as a lost content word.
    if w.endswith("e") and len(w) >= 4:
        w = w[:-1]
    return w


def _sentence_initial(text: str, start: int) -> bool:
    """Is the token at `start` the first word of a sentence?

    Capitalisation only says "proper noun" away from a sentence opening, so this is what
    keeps every sentence's first word out of the entity count.
    """
    i, quoted = start - 1, False
    while i >= 0 and (text[i].isspace() or text[i] in "\"'“”‘’([{"):
        quoted = quoted or not text[i].isspace()
        i -= 1
    if i < 0:
        return True
    # Past a quote mark, a comma or colon opens a sentence too: in `He said, "Ships are
    # slow"` the S is capitalised by the quotation, not because it names anything. Without
    # this, every line of dialogue donates its first word to the proper-noun count.
    return text[i] in (".!?,:" if quoted else ".!?")


def _entities(text: str) -> Counter:
    """Capitalised words that are not sentence-initial — a parser-free proper-noun proxy."""
    out: Counter = Counter()
    for m in WORD_RX.finditer(text):
        w = m.group(0)
        if w[0].isupper() and not _sentence_initial(text, m.start()):
            out[w] += 1
    return out


def _content_words(text: str) -> Counter:
    return Counter(_stem(w) for w in WORD_RX.findall(text)
                   if w.lower() not in _FUNCTION_SET and len(w) > 2)


def _marker_counts(text: str, markers: set[str]) -> int:
    n = sum(1 for w in WORD_RX.findall(text) if w.lower() in markers)
    if markers is NEGATIONS:
        n += len(re.findall(r"n't\b", text, re.IGNORECASE))
    return n


def _recall(source: Counter, rewrite: Counter) -> float:
    """How much of the source survived, as a multiset fraction. Empty source scores 1.0."""
    total = sum(source.values())
    if total == 0:
        return 1.0
    kept = sum(min(c, rewrite[k]) for k, c in source.items())
    return kept / total


def _symmetric(a: int, b: int) -> float:
    """For markers where ADDING is drift too — inventing a hedge changes the claim as
    surely as deleting one, so this penalises both directions."""
    hi = max(a, b)
    return 1.0 if hi == 0 else min(a, b) / hi


def preservation(source: str, rewrite: str) -> dict:
    """Did the rewrite keep what the source actually said? 0..1 per family.

    Five families, because "meaning" fails in distinguishable ways and a caller deserves
    to know which one:

      numbers    every figure, date, percentage and quantity in the source
      entities   proper nouns (capitalised away from a sentence opening)
      negation   negation markers, counted both ways — losing a "not" inverts a claim
      hedges     hedging and modality, counted both ways — see NEGATIONS/HEDGES above
      content    content-word retention, lightly stemmed

    `overall` is the MINIMUM, not the mean. Meaning preservation is conjunctive: a
    rewrite that drops every number is broken no matter how faithfully it kept the
    content words, and averaging would hand it a comfortable 0.8. The weakest family is
    the result, and `weakest` names it so the failure is legible rather than a bare score.
    """
    families = {
        "numbers": _recall(Counter(NUMBER_RX.findall(source)),
                           Counter(NUMBER_RX.findall(rewrite))),
        "entities": _recall(_entities(source), _entities(rewrite)),
        "negation": _symmetric(_marker_counts(source, NEGATIONS),
                               _marker_counts(rewrite, NEGATIONS)),
        "hedges": _symmetric(_marker_counts(source, HEDGES),
                             _marker_counts(rewrite, HEDGES)),
        "content": _recall(_content_words(source), _content_words(rewrite)),
    }
    weakest = min(PRESERVATION_FAMILIES, key=lambda f: families[f])
    # Unrounded on purpose. Everything in this module is asserted equal to the browser
    # port bit for bit, and rounding is where two implementations quietly diverge:
    # Python's round() breaks ties to even, JavaScript's Math.round() breaks them away
    # from zero, so a ratio like 1/32 rounds to 0.0312 here and 0.0313 there. Rounding
    # is a display decision; callers that want it can do it where the number is shown.
    return {
        "families": families,
        "overall": families[weakest],
        "weakest": weakest,
        "method": "lexical retention, not entailment",
    }


# --------------------------------------------------------------------- style movement --

# Mirrors vsRng in pages/voicespace.js exactly. The existing similarity_report uses
# random.Random, whose stream node cannot reproduce, so its intervals are allowed to
# differ between page and tool. A DELTA cannot afford that: the verdict turns on whether
# the interval excludes zero, so page and tool could disagree about whether a rewrite
# worked at all. This LCG is identical on both sides, and so are the intervals.
_LCG_MOD = 2 ** 32


def _lcg(seed: int):
    s = seed % _LCG_MOD

    def nxt() -> float:
        nonlocal s
        s = (s * 1664525 + 1013904223) % _LCG_MOD
        return s / _LCG_MOD
    return nxt


def _window_zs(text: str, population: Population) -> list[dict[str, float]]:
    ws = windows(text)
    return [population.standardize(w) for w in ws] or [population.standardize(text)]


def _overall(zs: list[dict[str, float]], region: VoiceRegion) -> float:
    zbar = {a: sum(z[a] for z in zs) / len(zs) for a in AXIS_NAMES}
    sims = axis_similarity(zbar, region)
    return 100.0 * sum(sims.values()) / len(AXIS_NAMES)


def style_delta(source: str, rewrite: str, region: VoiceRegion, population: Population,
                replicates: int = 400, confidence: float = 0.9, seed: int = 17) -> dict:
    """How far the rewrite moved toward `region`, with an interval on the movement.

    `delta` is signed: positive moved toward the voice, negative away. `closed` reports
    it as a fraction of the distance that was available to close, which is the fairer
    read — gaining 5 points from 40 is a different achievement from gaining 5 from 85.

    The interval is a bootstrap over both documents' own windows, resampled
    independently per replicate, so it carries the sampling noise of both sides. The
    verdict is deliberately conservative: `moved` is true only when the whole interval
    sits above zero. A delta of +9 whose interval runs [-4, +21] is reported as no
    measurable movement, because that is what it is.
    """
    z_src, z_out = _window_zs(source, population), _window_zs(rewrite, population)
    s_in, s_out = _overall(z_src, region), _overall(z_out, region)
    delta = s_out - s_in
    headroom = 100.0 - s_in
    closed = delta / headroom if headroom > 1e-9 else 0.0

    rnd = _lcg(seed)
    boot: list[float] = []
    # One window on either side cannot estimate its own variability; say so rather than
    # emitting a zero-width interval that reads as certainty.
    reliable = len(z_src) >= 3 and len(z_out) >= 3
    if reliable:
        for _ in range(replicates):
            pick_a = [z_src[int(rnd() * len(z_src))] for _ in range(len(z_src))]
            pick_b = [z_out[int(rnd() * len(z_out))] for _ in range(len(z_out))]
            boot.append(_overall(pick_b, region) - _overall(pick_a, region))

    lo_q, hi_q = (1 - confidence) / 2, 1 - (1 - confidence) / 2
    if len(boot) >= 2:
        v = sorted(boot)
        lo, hi = _percentile(v, lo_q), _percentile(v, hi_q)
    else:
        lo, hi = delta, delta

    return {   # unrounded — see preservation() on why
        "voice": region.name,
        "source": s_in,
        "rewrite": s_out,
        "delta": delta,
        "low": lo,
        "high": hi,
        "closed": closed,
        "confidence": confidence,
        "windows": [len(z_src), len(z_out)],
        "interval_reliable": reliable,
        "moved": bool(reliable and lo > 0),
        "regressed": bool(reliable and hi < 0),
    }


MEANING_FLOOR = 0.75


def grade(source: str, rewrite: str, region: VoiceRegion, population: Population,
          replicates: int = 400, confidence: float = 0.9, seed: int = 17) -> dict:
    """Both axes, side by side, never averaged.

    The verdict checks meaning FIRST and lets it veto. A rewrite that moved 14 points
    toward the voice while losing a third of the source's figures has not half-succeeded;
    it has failed in the way that matters most, and any ranking that lets style buy back
    meaning will eventually recommend it.
    """
    style = style_delta(source, rewrite, region, population, replicates, confidence, seed)
    meaning = preservation(source, rewrite)

    if meaning["overall"] < MEANING_FLOOR:
        verdict = f"meaning drift — {meaning['weakest']} preserved at {meaning['overall']:.2f}"
    elif style["moved"]:
        verdict = f"moved toward {region.name} by {style['delta']:+.1f} points"
    elif style["regressed"]:
        verdict = f"moved away from {region.name} by {style['delta']:+.1f} points"
    elif not style["interval_reliable"]:
        verdict = "too short to measure movement — one window cannot bound itself"
    else:
        verdict = (f"no measurable movement ({style['delta']:+.1f}, "
                   f"interval [{style['low']:+.1f}, {style['high']:+.1f}] spans zero)")

    return {"style": style, "meaning": meaning, "verdict": verdict,
            "meaning_floor": MEANING_FLOOR}
