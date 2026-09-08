"""Voice space: writing style as a vector of NAMED, INTERPRETABLE axes.

The difference from `metrics.score_text`
----------------------------------------
`score_text` returns SIMILARITIES — "how close is this text to that corpus on feature
family X". Those only mean anything relative to a baseline, they cannot be plotted, and
two voices cannot be compared without picking one of them as the reference.

This module returns COORDINATES. Every text becomes a point in a fixed, labelled space:
sentence length, subordination, nominalisation, punctuation variety, formality, and so
on — each an absolute measurement with a direction you can state in words. A voice is
then a region in that space (centroid plus spread), any two voices can be compared
directly, and the distance between them decomposes into "which axes differ, and by how
much" instead of collapsing to one number nobody can interrogate.

Standardisation is what makes the axes comparable. Raw units are incommensurable —
words-per-sentence runs 5-60, contraction rate runs 0-0.05 — so coordinates are
z-scored against a reference POPULATION (`Population.fit`), normally the benchmark
corpus. After that a coordinate means "this many standard deviations from typical
English prose", which is a statement a person can check.

What the benchmark then measures
--------------------------------
  * per-axis discrimination — which axes actually separate authors, and which are noise
  * effective dimensionality — how many independent axes voice really has. The axes are
    correlated (long sentences carry more commas), so 17 named dimensions are not 17
    degrees of freedom. `effective_dimensionality` reports the participation ratio of
    the correlation matrix's eigenvalues: the number of axes that behave independently.

No LLM, no dependencies. Eigenvalues come from power iteration on the correlation matrix.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from revoice.voicemetric.features import CONTRACTION_RX, fingerprint, tokenize

FIRST_PERSON = {"i", "me", "my", "mine", "we", "us", "our", "ours"}
SECOND_PERSON = {"you", "your", "yours"}


@dataclass(frozen=True)
class Axis:
    """One interpretable dimension: how it is measured and what each end means."""

    name: str
    low: str          # what a low value reads as
    high: str         # what a high value reads as
    family: str       # rhythm | structure | lexis | syntax | punctuation | stance


# The space. Deliberately small and readable: every axis is something a writer could
# recognise in their own prose and an editor could change on purpose.
AXES: tuple[Axis, ...] = (
    Axis("sentence_length", "clipped", "long-breathed", "rhythm"),
    Axis("sentence_variance", "metronomic", "varied", "rhythm"),
    Axis("paragraph_length", "short paragraphs", "long paragraphs", "structure"),
    Axis("sentences_per_paragraph", "one-idea paragraphs", "developed paragraphs", "structure"),
    Axis("word_length", "plain words", "long words", "lexis"),
    Axis("lexical_richness", "repetitive", "wide vocabulary", "lexis"),
    Axis("readability", "demanding", "easy", "lexis"),
    Axis("subordination", "coordinate", "subordinate-heavy", "syntax"),
    Axis("nominalization", "verbal", "abstract-nouny", "syntax"),
    Axis("passivity", "active", "passive", "syntax"),
    Axis("adverbial", "spare", "-ly heavy", "syntax"),
    Axis("comma_density", "unpunctuated", "comma-heavy", "punctuation"),
    Axis("punctuation_variety", "commas only", "semicolons/dashes/colons", "punctuation"),
    Axis("conjunction_openings", "formal openings", "and/but openings", "stance"),
    Axis("contraction", "formal", "conversational", "stance"),
    Axis("first_person", "impersonal", "first-person", "stance"),
    Axis("second_person", "no address", "addresses the reader", "stance"),
)

AXIS_NAMES: tuple[str, ...] = tuple(a.name for a in AXES)


def coordinates(text: str) -> dict[str, float]:
    """Raw, absolute coordinates for one text. Units differ per axis by design;
    `Population.standardize` is what makes them comparable."""
    fp = fingerprint(text)
    words, _sentences = tokenize(text)
    n_words = max(len(words), 1)

    punct = fp["punct_per_sentence"]
    comma = punct.get(",", 0.0)
    variety = punct.get(";", 0.0) + punct.get(":", 0.0) + punct.get("—", 0.0) + punct.get("–", 0.0)

    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    para_lens = [len(re.findall(r"[a-zA-Z']+", p)) for p in paras] or [n_words]

    return {
        "sentence_length": fp["mean_sentence_len"],
        "sentence_variance": fp["burstiness"],
        "paragraph_length": sum(para_lens) / len(para_lens),
        "sentences_per_paragraph": fp["mean_sents_per_para"],
        "word_length": fp["mean_word_len"],
        # Yule's K falls as vocabulary widens, so invert it to keep every axis pointing
        # the same way: higher always means "more of what the axis name says".
        "lexical_richness": -fp["yules_k"],
        "readability": fp["flesch"],
        "subordination": fp["subordinator_rate"] * 100,
        "nominalization": fp["nominalization_rate"] * 100,
        "passivity": fp["passive_rate"],
        "adverbial": fp["adverb_ly_rate"] * 100,
        "comma_density": comma,
        "punctuation_variety": variety,
        "conjunction_openings": fp["conjunction_start_rate"] * 100,
        "contraction": len(CONTRACTION_RX.findall(text)) / n_words * 100,
        "first_person": sum(1 for w in words if w in FIRST_PERSON) / n_words * 100,
        "second_person": sum(1 for w in words if w in SECOND_PERSON) / n_words * 100,
    }


def _mean_std(xs: list[float]) -> tuple[float, float]:
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / len(xs)
    return m, math.sqrt(v)


@dataclass
class Population:
    """The reference distribution that turns raw coordinates into z-scores.

    Fit this on a broad corpus — the benchmark's 70 authors across 11 genres — so that
    "+1.4 on subordination" means "more subordinate than typical English prose" rather
    than "more subordinate than whatever happened to be handy".
    """

    stats: dict[str, tuple[float, float]] = field(default_factory=dict)
    n: int = 0

    @classmethod
    def fit(cls, texts: list[str]) -> Population:
        coords = [coordinates(t) for t in texts]
        stats = {}
        for axis in AXIS_NAMES:
            m, sd = _mean_std([c[axis] for c in coords])
            stats[axis] = (m, max(sd, 1e-9))
        return cls(stats=stats, n=len(coords))

    def standardize(self, text_or_coords) -> dict[str, float]:
        """Coordinates in standard deviations from the population mean."""
        c = text_or_coords if isinstance(text_or_coords, dict) else coordinates(text_or_coords)
        return {a: (c[a] - self.stats[a][0]) / self.stats[a][1] for a in AXIS_NAMES}

    def to_dict(self) -> dict:
        return {"n": self.n, "stats": {a: list(v) for a, v in self.stats.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> Population:
        return cls(stats={a: tuple(v) for a, v in d["stats"].items()}, n=d.get("n", 0))


# No author is perfectly consistent on any axis, and a reference set that says otherwise
# is telling us about the sample, not the writer. Coordinates are already in population
# standard deviations, so a floor of 0.15 means "at least 15% of the general spread".
# Without it a voice fitted on near-identical texts gets spread ~0, and deviations
# divided by that come back in the millions with every similarity underflowing to zero —
# the same failure the Burrows' Delta code guards against in `metrics`.
MIN_SPREAD = 0.15


@dataclass
class VoiceRegion:
    """A voice as a region in the space: where it sits, and how much it moves."""

    name: str
    centroid: dict[str, float]
    spread: dict[str, float]
    n: int

    @classmethod
    def fit(cls, name: str, texts: list[str], population: Population) -> VoiceRegion:
        zs = [population.standardize(t) for t in texts]
        centroid, spread = {}, {}
        for axis in AXIS_NAMES:
            m, sd = _mean_std([z[axis] for z in zs])
            centroid[axis] = m
            spread[axis] = max(sd, MIN_SPREAD)
        return cls(name=name, centroid=centroid, spread=spread, n=len(zs))

    def distance(self, text_or_z, population: Population | None = None,
                 normalize: bool = True) -> float:
        """Distance from this voice's centre, in standard deviations.

        `normalize` divides each axis by the voice's OWN spread on that axis, which is
        the difference between "far from this author" and "unusual in general": an
        author who varies wildly in sentence length should not be surprised by a sample
        that varies wildly in sentence length.
        """
        z = text_or_z if isinstance(text_or_z, dict) else population.standardize(text_or_z)
        total = 0.0
        for axis in AXIS_NAMES:
            d = z[axis] - self.centroid[axis]
            if normalize:
                d /= self.spread[axis]
            total += d * d
        return math.sqrt(total / len(AXIS_NAMES))

    def deviations(self, text_or_z, population: Population | None = None) -> list[tuple[str, float]]:
        """Per-axis signed deviation, largest first — the interrogable part.

        This is what a scalar score cannot give you: not "72/100" but "your sentences
        are 1.8 sd longer than usual and you are using half your normal semicolons".
        """
        z = text_or_z if isinstance(text_or_z, dict) else population.standardize(text_or_z)
        out = [(a, (z[a] - self.centroid[a]) / self.spread[a]) for a in AXIS_NAMES]
        return sorted(out, key=lambda kv: -abs(kv[1]))


# ---------- similarity with uncertainty ----------

BOOTSTRAP_REPLICATES = 400
MIN_WINDOWS = 3


def windows(text: str, target_words: int = 220) -> list[str]:
    """Split a document into comparable chunks on paragraph boundaries.

    These are the resampling unit for the bootstrap. Paragraphs, not sentences: a
    paragraph is roughly the smallest span at which paragraph-shape and rhythm axes
    mean anything.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return []
    out, cur, count = [], [], 0
    for p in paras:
        cur.append(p)
        count += len(p.split())
        if count >= target_words:
            out.append("\n\n".join(cur))
            cur, count = [], 0
    if cur:
        tail = "\n\n".join(cur)
        if out and count < target_words // 2:
            out[-1] += "\n\n" + tail   # avoid a runt window skewing the resample
        else:
            out.append(tail)
    return out


def axis_similarity(z: dict[str, float], region: VoiceRegion) -> dict[str, float]:
    """Per-axis similarity in (0, 1]: 1.0 sits exactly on the voice's centre.

    exp(-|deviation|) in units of the voice's own spread, so "one of this author's
    usual standard deviations away" always means the same thing on every axis and the
    axes stay comparable to each other.
    """
    return {a: math.exp(-abs(z[a] - region.centroid[a]) / region.spread[a]) for a in AXIS_NAMES}


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    idx = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(idx)), int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def similarity_report(text: str, region: VoiceRegion, population: Population,
                      replicates: int = BOOTSTRAP_REPLICATES, confidence: float = 0.9,
                      seed: int = 17) -> dict:
    """Overall and per-axis similarity to a voice, each with a confidence interval.

    The interval comes from a bootstrap over the document's own paragraphs: resample
    windows with replacement, recompute, and take percentiles. It answers the question
    a single score cannot — *how much would this move if I had been handed a different
    few pages of the same document?* A wide interval on a short or internally mixed
    text is the honest result, and it is exactly the case where a bare number misleads.

    Documents too short to window are still scored, with `interval_reliable` false:
    one window cannot estimate its own variability.
    """
    import random

    ws = windows(text)
    zs = [population.standardize(w) for w in ws] or [population.standardize(text)]
    point_z = {a: sum(z[a] for z in zs) / len(zs) for a in AXIS_NAMES}
    point_axis = axis_similarity(point_z, region)
    point_overall = 100.0 * sum(point_axis.values()) / len(AXIS_NAMES)

    rng = random.Random(seed)
    boot_overall: list[float] = []
    boot_axis: dict[str, list[float]] = {a: [] for a in AXIS_NAMES}
    if len(zs) >= MIN_WINDOWS:
        n = len(zs)
        for _ in range(replicates):
            pick = [zs[rng.randrange(n)] for _ in range(n)]
            zbar = {a: sum(z[a] for z in pick) / n for a in AXIS_NAMES}
            sims = axis_similarity(zbar, region)
            boot_overall.append(100.0 * sum(sims.values()) / len(AXIS_NAMES))
            for a in AXIS_NAMES:
                boot_axis[a].append(sims[a])

    lo_q, hi_q = (1 - confidence) / 2, 1 - (1 - confidence) / 2

    def interval(vals: list[float], point: float) -> tuple[float, float]:
        if len(vals) < 2:
            return point, point
        v = sorted(vals)
        return _percentile(v, lo_q), _percentile(v, hi_q)

    o_lo, o_hi = interval(boot_overall, point_overall)
    axes = {}
    for a in AXIS_NAMES:
        lo, hi = interval(boot_axis[a], point_axis[a])
        axes[a] = {
            "similarity": round(point_axis[a], 4),
            "low": round(lo, 4),
            "high": round(hi, 4),
            # signed, in the voice's own spread: which way, not just how far
            "deviation": round((point_z[a] - region.centroid[a]) / region.spread[a], 3),
        }
    return {
        "voice": region.name,
        "overall": round(point_overall, 1),
        "low": round(o_lo, 1),
        "high": round(o_hi, 1),
        "confidence": confidence,
        "windows": len(zs),
        "words": len(text.split()),
        "interval_reliable": len(zs) >= MIN_WINDOWS,
        "axes": axes,
    }


# ---------- structure of the space itself ----------


def correlation_matrix(samples: list[dict[str, float]]) -> list[list[float]]:
    """Pearson correlation between every pair of axes, over standardized samples."""
    cols = {a: [s[a] for s in samples] for a in AXIS_NAMES}
    stats = {a: _mean_std(v) for a, v in cols.items()}
    k = len(AXIS_NAMES)
    m = [[0.0] * k for _ in range(k)]
    for i, a in enumerate(AXIS_NAMES):
        ma, sa = stats[a]
        for j, b in enumerate(AXIS_NAMES):
            mb, sb = stats[b]
            cov = sum((x - ma) * (y - mb) for x, y in zip(cols[a], cols[b], strict=True)) / len(samples)
            m[i][j] = cov / (sa * sb) if sa > 1e-12 and sb > 1e-12 else 0.0
    return m


def eigenvalues(matrix: list[list[float]], iterations: int = 300) -> list[float]:
    """Eigenvalues of a small symmetric matrix, by power iteration with deflation.

    A 17x17 correlation matrix does not justify a linear-algebra dependency, but the
    naive version of this is wrong in a way that is easy to miss: deflating the matrix
    and then restarting power iteration from the SAME vector fails whenever that vector
    lands in the deflated null space. On the identity matrix it returns [1, 0, 0, 0]
    instead of [1, 1, 1, 1], and a wrong eigenvalue spectrum silently corrupts every
    effective-dimensionality figure downstream.

    So: keep the eigenvectors found so far, project them out of both the starting vector
    and each iterate, and vary the start per round. Deterministic, no random seed.
    """
    k = len(matrix)
    found: list[list[float]] = []
    out: list[float] = []

    def _orthogonalize(v: list[float]) -> list[float]:
        # twice: one pass of Gram-Schmidt loses orthogonality to rounding, and the
        # whole point here is that the deflated directions stay gone
        for _ in range(2):
            for u in found:
                dot = sum(v[i] * u[i] for i in range(k))
                v = [v[i] - dot * u[i] for i in range(k)]
        return v

    def _start() -> list[float] | None:
        """First basis vector that survives orthogonalisation against what we have.

        Basis vectors are used rather than a smooth formula because a smooth one does
        not span: sin(c + i*d) is a two-parameter family, so after two deflations every
        such start already lies in the span of the vectors just removed, and the
        iteration stalls at zero. e_0..e_k-1 always span.
        """
        for b in range(k):
            v = _orthogonalize([1.0 if i == b else 0.0 for i in range(k)])
            norm = math.sqrt(sum(x * x for x in v))
            if norm > 1e-9:
                return [x / norm for x in v]
        # Unreachable: the loop below runs at most k times, and fewer than k orthonormal
        # vectors cannot span R^k, so some basis vector always survives. Kept as a guard
        # rather than an assumption.
        return None  # pragma: no cover

    for _round in range(k):
        v = _start()
        if v is None:  # pragma: no cover - see _start
            break

        val = 0.0
        for _ in range(iterations):
            w = [sum(matrix[i][j] * v[j] for j in range(k)) for i in range(k)]
            w = _orthogonalize(w)
            norm = math.sqrt(sum(x * x for x in w))
            if norm < 1e-12:
                val = 0.0
                break
            nv = [x / norm for x in w]
            if max(abs(nv[i] - v[i]) for i in range(k)) < 1e-12:
                v, val = nv, norm
                break
            v, val = nv, norm

        if val <= 1e-9:
            break
        out.append(val)
        found.append(v)
    return sorted(out, reverse=True)


def effective_dimensionality(samples: list[dict[str, float]]) -> dict:
    """How many independent axes does voice actually have here?

    The named axes are correlated — longer sentences carry more commas, abstract nouns
    travel with the passive — so 17 labels are not 17 degrees of freedom. The
    participation ratio (sum(l)^2 / sum(l^2) over the correlation eigenvalues) answers
    "how many axes are pulling their own weight", and the top eigenvalue's share says
    how much of the variation is really one general factor.
    """
    if len(samples) < 3:
        return {"axes": len(AXIS_NAMES), "effective": float("nan"), "top_share": float("nan")}
    vals = [v for v in eigenvalues(correlation_matrix(samples)) if v > 1e-9]
    total = sum(vals)
    if total <= 0:
        return {"axes": len(AXIS_NAMES), "effective": float("nan"), "top_share": float("nan")}
    pr = (total ** 2) / sum(v * v for v in vals)
    return {
        "axes": len(AXIS_NAMES),
        "effective": round(pr, 2),
        "top_share": round(vals[0] / total, 3),
        "eigenvalues": [round(v, 3) for v in vals[:8]],
    }
