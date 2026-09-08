"""Corpus baselines and the composite voice-match score.

Pure measurement: give it texts, get back a baseline or a score. Reading files and
knowing what a voice pack is belong to the caller — see `revoice.core.metrics` for the
pack-aware wrappers this module is deliberately free of.

  baseline_from_texts        aggregate a reference distribution from documents
  score_text                 one text against one baseline -> per-component + composite
  calibration_from_texts     self-scores, leave-one-out and bucketed by span length
  span_floor                 the on-target threshold for a span of a given length

The composite weights are FITTED (`voicemetric.bench --fit`), not hand-picked, and
`vocab` is held at zero by construction — see VOICE_COMPONENTS.
"""

from __future__ import annotations

import math
from collections import Counter

from revoice.voicemetric.features import (
    FUNCTION_WORDS,
    OPENER_CLASSES,
    char_ngram_profile,
    content_terms,
    cosine,
    fingerprint,
    function_word_bigram_profile,
    tfidf_vector,
    word_bigram_profile,
)

RICHNESS_SCALARS = ["yules_k", "mtld", "mean_word_len", "flesch"]
SYNTAX_SCALARS = ["subordinator_rate", "conjunction_start_rate", "nominalization_rate",
                  "passive_rate", "adverb_ly_rate"]
STRUCTURE_SCALARS = ["mean_para_len", "mean_sents_per_para", "mean_sentence_len",
                     "sentence_len_std", "burstiness"]
PUNCT_RATIO_SCALARS = ["semicolon_per_comma", "dash_per_comma", "colon_per_comma",
                       "contraction_rate", "hyphen_rate"]
SCALARS = RICHNESS_SCALARS + SYNTAX_SCALARS + STRUCTURE_SCALARS + PUNCT_RATIO_SCALARS

PUNCTS = list(",;:—–()!?\"'*")

COMPONENTS = ("delta", "ngram", "fwbigram", "opener", "syntax",
              "structure", "rhythm", "richness", "punct", "vocab")

# Components eligible for an AUTHORSHIP score. `vocab` is excluded by construction,
# not by its measured performance — measured, it is the single best component on
# every corpus we have, which is exactly the problem. Work-level leave-one-out stops
# a query's own work leaking into its reference, but it cannot stop an author's whole
# body of work from being topically coherent, so tf-idf keeps scoring authorship it
# is not measuring. Letting a fitter see it produces a flattering number that will not
# survive the author writing about something new. It stays computed for exemplar
# retrieval, where topic similarity is the point.
VOICE_COMPONENTS = tuple(c for c in COMPONENTS if c != "vocab")

# Default weighting, FITTED by `revoice bench --fit` on the full evaluation corpus —
# 70 authors, 11 genres, hard negatives (different author, SAME genre), work-level
# leave-one-out — and scored on held-out reference models. Not hand-picked.
#
# This replaces weights fitted on four humorists alone, which did not generalise: on
# the 70-author corpus they scored 0.631, below plain equal weighting at 0.648. Fitting
# on one genre buys performance in that genre and loses it everywhere else.
#
# What survives across both fits: `punct` and `delta` — the two families that are
# content-independent by construction — carry the score. `rhythm`, `opener`, `syntax`
# and `structure` fit to zero on the larger corpus. `ngram` returns with modest weight
# once the corpus is broad enough that it cannot simply memorise one genre's vocabulary.
# `vocab` is zero by construction, never by measurement (see VOICE_COMPONENTS).
WEIGHTS = {"delta": 0.318, "ngram": 0.181, "fwbigram": 0.0, "opener": 0.0,
           "syntax": 0.0, "structure": 0.064, "rhythm": 0.0, "richness": 0.104,
           "punct": 0.332, "vocab": 0.0}

MIN_WORDS_RELIABLE = 150


def _mean_std(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / len(xs)
    return m, math.sqrt(v)


# ---------- baseline building ----------

def baseline_from_texts(texts: list[str]) -> dict:
    """Build one baseline from a list of documents. The unit of aggregation is the
    DOCUMENT: per-feature mean/std across documents, plus corpus-level centroids.

    Split out of `build_baselines` so callers that have texts but no voice pack —
    notably `core.bench`, which builds leave-one-out baselines by the hundred — can
    reuse the exact code path that `learn` uses. Same inputs, same numbers.
    """
    fps = [fingerprint(t) for t in texts]
    if not fps:
        return {}

    # function words: per-word mean/std across docs
    fw = {}
    for w in FUNCTION_WORDS:
        m, s = _mean_std([fp["function_word_freq"].get(w, 0.0) for fp in fps])
        fw[w] = [round(m, 6), round(max(s, 1e-6), 6)]

    # scalars
    scalars = {}
    for k in SCALARS:
        m, s = _mean_std([fp.get(k, 0.0) for fp in fps])
        scalars[k] = [round(m, 4), round(max(s, 1e-6), 4)]

    # sentence-length and paragraph-length histogram centroids
    def _hist_centroid(key):
        # fps is non-empty (guarded above) and fingerprint() always emits both
        # histograms at full bin width, so there is nothing to defend against here.
        hs = [fp[key] for fp in fps]
        return [round(sum(h[i] for h in hs) / len(hs), 4) for i in range(len(hs[0]))]

    hist_centroid = _hist_centroid("sent_len_hist")
    para_centroid = _hist_centroid("para_len_hist")

    # sentence-opener class distribution centroid
    opener = {}
    for k in OPENER_CLASSES:
        m, sd = _mean_std([fp.get("opener_dist", {}).get(k, 0.0) for fp in fps])
        opener[k] = [round(m, 4), round(max(sd, 1e-4), 4)]

    # punctuation centroid
    punct = {}
    for p in PUNCTS:
        m, s = _mean_std([fp["punct_per_sentence"].get(p, 0.0) for fp in fps])
        punct[p] = [round(m, 4), round(max(s, 1e-6), 4)]

    # tf-idf + n-gram centroids
    df: Counter = Counter()
    doc_terms = []
    char_cent: dict[str, float] = {}
    bigram_cent: dict[str, float] = {}
    fwbi_cent: dict[str, float] = {}
    for text in texts:
        terms = content_terms(text)
        doc_terms.append(terms)
        df.update(terms.keys())
        for k, v in char_ngram_profile(text).items():
            char_cent[k] = char_cent.get(k, 0.0) + v
        for k, v in word_bigram_profile(text).items():
            bigram_cent[k] = bigram_cent.get(k, 0.0) + v
        for k, v in function_word_bigram_profile(text).items():
            fwbi_cent[k] = fwbi_cent.get(k, 0.0) + v
    n_texts = max(len(texts), 1)
    char_cent = dict(sorted(((k, v / n_texts) for k, v in char_cent.items()),
                            key=lambda kv: -kv[1])[:400])
    bigram_cent = dict(sorted(((k, v / n_texts) for k, v in bigram_cent.items()),
                              key=lambda kv: -kv[1])[:300])
    fwbi_cent = dict(sorted(((k, v / n_texts) for k, v in fwbi_cent.items()),
                            key=lambda kv: -kv[1])[:200])
    n_docs = max(len(doc_terms), 1)
    centroid: dict[str, float] = {}
    for terms in doc_terms:
        vec = tfidf_vector(terms, df, n_docs)
        for k, v in vec.items():
            centroid[k] = centroid.get(k, 0.0) + v / n_docs
    top_centroid = dict(sorted(centroid.items(), key=lambda kv: -kv[1])[:400])

    return {
        "doc_count": len(texts),
        "function_words": fw,
        "scalars": scalars,
        "sent_len_hist": hist_centroid,
        "para_len_hist": para_centroid,
        "opener": opener,
        "punct": punct,
        "df": dict(df),
        "n_docs": n_docs,
        "tfidf_centroid": {k: round(v, 6) for k, v in top_centroid.items()},
        "char_ngrams": {k: round(v, 6) for k, v in char_cent.items()},
        "word_bigrams": {k: round(v, 6) for k, v in bigram_cent.items()},
        "fw_bigrams": {k: round(v, 6) for k, v in fwbi_cent.items()},
    }


# Span-length buckets for calibration. A score is length-dependent, so a band measured
# on whole documents is the wrong ruler for a paragraph — that mismatch is what made
# the pipeline classify 79% of the author's own paragraphs as "rewrite".
# Buckets are RANGES, and the calibration windows are sampled across each range
# rather than at its edge. Sampling only at the boundary leaves a residual version of
# the same units error: a 29-word span would be judged against a band measured on
# 40-word windows, and since the score climbs with length that reads as off-target.
SPAN_BUCKETS = ((25, 40), (40, 80), (80, 160), (160, 320), (320, 640))
LOO_MAX_DOCS = 12          # cap the O(n^2) leave-one-out passes
SPAN_SAMPLES_PER_BUCKET = 24


def _bucket_for(words: int) -> int:
    """The calibration bucket a span of this length belongs to, keyed by its upper edge."""
    for _lo, hi in SPAN_BUCKETS:
        if words <= hi:
            return hi
    return SPAN_BUCKETS[-1][1]


def _windows_of(text: str, lo: int, hi: int, count: int, rng) -> list[str]:
    """Sample `count` windows with lengths drawn uniformly from [lo, hi]."""
    words = text.split()
    out = []
    for _ in range(count):
        n = rng.randint(lo, hi)
        if len(words) <= n:
            continue
        start = rng.randrange(0, len(words) - n)
        out.append(" ".join(words[start:start + n]))
    return out


def calibration_from_texts(baselines: dict, texts_by_register: dict[str, list[str]],
                           progress=None) -> dict:
    """Per-register self-scores, LEAVE-ONE-OUT and bucketed by span length.

    Takes register -> texts. Reading files and knowing what a voice pack is are the
    caller's business; this module only measures.

    Two corrections over the previous version, both of which the bench made visible:

    1. **Leave-one-out.** Scoring a document against a baseline that contains it lets
       the document pull the centroid toward itself, so the band lands too high and too
       tight and every real candidate then looks worse than it is.
    2. **Per span length.** The old band was measured on whole documents and applied to
       individual spans. Since the composite moves with length, that compared two
       different quantities; `pipeline` now looks up the band for the span it is judging.
    """
    import random

    rng = random.Random(17)
    calib: dict[str, dict] = {}

    for register, texts in texts_by_register.items():
        if not texts:
            continue

        step = max(1, len(texts) // LOO_MAX_DOCS)
        sampled = list(range(0, len(texts), step))[:LOO_MAX_DOCS]

        doc_scores: list[float] = []
        span_scores: dict[int, list[float]] = {hi: [] for _, hi in SPAN_BUCKETS}
        for i in sampled:
            rest = texts[:i] + texts[i + 1:]
            if len(rest) < 2:
                continue
            held = baseline_from_texts(rest)
            doc_scores.append(score_text(texts[i], held)["composite"])
            per = max(1, SPAN_SAMPLES_PER_BUCKET // len(sampled))
            for lo, hi in SPAN_BUCKETS:
                for w in _windows_of(texts[i], lo, hi, per, rng):
                    span_scores[hi].append(score_text(w, held)["composite"])

        if not doc_scores:  # single-document register: nothing to hold out
            doc_scores = [score_text(t, baselines[register])["composite"] for t in texts]

        m, sd = _mean_std(doc_scores)
        entry = {"self_mean": round(m, 1), "self_std": round(sd, 1),
                 "self_min": round(min(doc_scores), 1), "leave_one_out": len(sampled) > 1,
                 "spans": {}}
        for b, scores in span_scores.items():
            if len(scores) >= 3:
                bm, bsd = _mean_std(scores)
                entry["spans"][str(b)] = {"mean": round(bm, 1), "std": round(bsd, 1),
                                          "n": len(scores)}
        calib[register] = entry
        if progress:
            bands = " ".join(f"{b}w:{v['mean']:.0f}" for b, v in entry["spans"].items())
            progress(register, f"self {m:.1f}±{sd:.1f} (LOO) · spans {bands}")

    return calib


def span_floor(calibration: dict, register: str, words: int, sigma: float = 1.0) -> float | None:
    """The on-target threshold for a span of this length: bucket mean minus `sigma` std.

    Falls back to the nearest band the corpus actually produced, preferring a SHORTER
    one. Scores rise with length, so a shorter bucket's band is a lower bar — erring
    that way keeps the author's own text untouched, which is the failure we care about.
    Returns None only when the register has no span bands at all, so callers can decline
    to judge rather than reuse a number measured on a different unit.
    """
    spans = (calibration.get(register) or {}).get("spans", {})
    if not spans:
        return None
    available = sorted(int(k) for k in spans)
    target = _bucket_for(words)
    lower = [b for b in available if b <= target]
    band = spans[str(lower[-1] if lower else available[0])]
    return band["mean"] - sigma * band["std"]


def _scalar_similarity(fp: dict, baseline: dict, keys: list[str]) -> float:
    """Mean z-similarity over a group of scalar features. exp(-|z|) per feature.

    The variance floor matters: with a handful of reference documents an unlucky
    feature can have near-zero measured spread, which would otherwise turn a trivial
    difference into an infinite z.
    """
    sims = []
    for k in keys:
        stat = baseline.get("scalars", {}).get(k)
        if not stat:
            continue
        m, sd = stat
        sims.append(math.exp(-abs(fp.get(k, 0.0) - m) / max(sd, abs(m) * 0.25 + 1e-6)))
    return sum(sims) / len(sims) if sims else 0.0


def _hist_similarity(a: list[float], b: list[float]) -> float:
    """L1 histogram similarity, 1 = identical distribution."""
    if not a or not b:
        return 0.0
    return max(0.0, 1 - sum(abs(x - y) for x, y in zip(a, b, strict=False)) / 2)


def score_text(text: str, baseline: dict) -> dict:
    """Score one text against one baseline. Returns per-component scores + composite 0-100.

    Every component is a similarity in [0, 1] measuring one FAMILY of habits, so the
    bench can ablate them independently and the weights can be fitted rather than
    guessed. See docs/metrics.md for what each is worth.
    """
    fp = fingerprint(text)

    # --- delta: Burrows' Delta on function-word z-scores ---
    # Variance floor prevents blow-ups on small/homogeneous corpora: std is floored
    # at 15% of the mean plus a small absolute term.
    zs = []
    for w, (m, sd) in baseline["function_words"].items():
        f = fp["function_word_freq"].get(w, 0.0)
        zs.append(abs(f - m) / max(sd, 0.15 * m + 5e-4))
    delta = sum(zs) / len(zs) if zs else 99.0
    delta_sim = math.exp(-delta / 1.5)  # 0..1, ~0.5 at delta ~ 1

    # --- ngram: char 3-gram + word bigram cosine vs the register centroids ---
    cn = cosine(char_ngram_profile(text), baseline.get("char_ngrams", {}))
    wb = cosine(word_bigram_profile(text), baseline.get("word_bigrams", {}))
    ngram = 0.6 * cn + 0.4 * wb

    # --- fwbigram: function-word bigrams only. Content-free joinery habits. ---
    fwbigram = cosine(function_word_bigram_profile(text), baseline.get("fw_bigrams", {}))

    # --- opener: how sentences are started, as a class distribution ---
    b_open = baseline.get("opener", {})
    opener = 0.0
    if b_open:
        sims = []
        for k in OPENER_CLASSES:
            m, sd = b_open.get(k, [0.0, 1e-4])
            sims.append(math.exp(-abs(fp.get("opener_dist", {}).get(k, 0.0) - m)
                                 / max(sd, 0.03)))
        opener = sum(sims) / len(sims)

    # --- grouped scalar families ---
    syntax = _scalar_similarity(fp, baseline, SYNTAX_SCALARS)
    richness = _scalar_similarity(fp, baseline, RICHNESS_SCALARS)

    # --- structure: paragraph shape (histogram + scalars) ---
    structure = 0.5 * _hist_similarity(fp.get("para_len_hist", []),
                                       baseline.get("para_len_hist") or []) \
        + 0.5 * _scalar_similarity(fp, baseline, STRUCTURE_SCALARS)

    # --- rhythm: sentence-length distribution ---
    rhythm = _hist_similarity(fp["sent_len_hist"], baseline.get("sent_len_hist") or [])

    # --- punct: per-sentence rates plus the scale-free ratios between marks ---
    psims = []
    for p, (m, sd) in baseline.get("punct", {}).items():
        f = fp["punct_per_sentence"].get(p, 0.0)
        psims.append(math.exp(-abs(f - m) / max(sd, 0.05)))
    rate_sim = sum(psims) / len(psims) if psims else 0.0
    punct = 0.5 * rate_sim + 0.5 * _scalar_similarity(fp, baseline, PUNCT_RATIO_SCALARS)

    # --- vocab: tf-idf cosine. Topical, kept for retrieval, weighted 0 for voice. ---
    vec = tfidf_vector(content_terms(text), baseline.get("df", {}), baseline.get("n_docs", 1))
    vocab = cosine(vec, baseline.get("tfidf_centroid", {}))

    comps = {"delta": delta_sim, "ngram": ngram, "fwbigram": fwbigram, "opener": opener,
             "syntax": syntax, "structure": structure, "rhythm": rhythm,
             "richness": richness, "punct": punct, "vocab": vocab}
    composite = 100 * sum(WEIGHTS.get(k, 0.0) * v for k, v in comps.items())

    return {
        "fingerprint": fp,
        "burrows_delta": round(delta, 3),
        "components": {k: round(v, 3) for k, v in comps.items()},
        "composite": round(composite, 1),
        "reliable": fp["words"] >= MIN_WORDS_RELIABLE,
    }


