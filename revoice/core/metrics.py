"""Voice-match metrics: how close is a document to a voice register's baseline?

Baselines are built during `learn` from corpus fingerprints (params/baselines.json).
All metrics are deterministic descriptive statistics:

  delta     Burrows' Delta on function-word z-scores (authorship-attribution standard;
            effectively a standardized linear discriminator). Lower = closer.
  rhythm    L1 similarity between sentence-length histograms.
  vocab     tf-idf cosine similarity vs the register's corpus centroid.
  punct     similarity of per-sentence punctuation rates.
  shape     similarity on scalar features (word len, TTR, adverbs, nominalizations,
            passive rate, flesch) via z-scores.

Composite: weighted blend → 0-100 "voice match" with per-component breakdown.
Calibration is relative: compare a doc's score to `learn`-reported self-scores
(the corpus scored against its own baseline) rather than treating numbers as absolute.
"""

from __future__ import annotations

import json
import math
from collections import Counter

from revoice.core.ingest import extract_text
from revoice.core.stylometry import (
    FUNCTION_WORDS,
    char_ngram_profile,
    content_terms,
    cosine,
    fingerprint,
    tfidf_vector,
    word_bigram_profile,
)
from revoice.core.voicepack import VoicePack

SCALARS = [
    "mean_sentence_len", "sentence_len_std", "burstiness", "mean_word_len",
    "type_token_ratio", "hapax_ratio", "adverb_ly_rate", "nominalization_rate",
    "passive_rate", "flesch",
]
PUNCTS = list(",;:—–()!?\"'*")
WEIGHTS = {"delta": 0.25, "ngram": 0.25, "rhythm": 0.15, "vocab": 0.10, "punct": 0.10, "shape": 0.15}
MIN_WORDS_RELIABLE = 150


def _mean_std(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / len(xs)
    return m, math.sqrt(v)


# ---------- baseline building (called from learn) ----------

def build_baselines(pack: VoicePack, progress=None) -> dict:
    """Aggregate per-register baselines from index fingerprints + corpus tf-idf."""
    index = pack.read_index()
    by_register: dict[str, list[dict]] = {}
    for e in index.values():
        by_register.setdefault(e["register"], []).append(e)

    baselines = {}
    for register, entries in by_register.items():
        fps = [e["fingerprint"] for e in entries if e.get("fingerprint")]
        if not fps:
            continue

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

        # sentence-length histogram centroid
        hists = [fp["sent_len_hist"] for fp in fps if fp.get("sent_len_hist")]
        n_bins = len(hists[0]) if hists else 0
        hist_centroid = [round(sum(h[i] for h in hists) / len(hists), 4) for i in range(n_bins)]

        # punctuation centroid
        punct = {}
        for p in PUNCTS:
            m, s = _mean_std([fp["punct_per_sentence"].get(p, 0.0) for fp in fps])
            punct[p] = [round(m, 4), round(max(s, 1e-6), 4)]

        # tf-idf + n-gram centroids over the register's docs
        df: Counter = Counter()
        doc_terms = []
        char_cent: dict[str, float] = {}
        bigram_cent: dict[str, float] = {}
        n_texts = 0
        for e in entries:
            text = extract_text(pack.training_dir / e["path"])
            if not text:
                continue
            n_texts += 1
            terms = content_terms(text)
            doc_terms.append(terms)
            df.update(terms.keys())
            for k, v in char_ngram_profile(text).items():
                char_cent[k] = char_cent.get(k, 0.0) + v
            for k, v in word_bigram_profile(text).items():
                bigram_cent[k] = bigram_cent.get(k, 0.0) + v
        n_texts = max(n_texts, 1)
        char_cent = dict(sorted(((k, v / n_texts) for k, v in char_cent.items()),
                                key=lambda kv: -kv[1])[:400])
        bigram_cent = dict(sorted(((k, v / n_texts) for k, v in bigram_cent.items()),
                                  key=lambda kv: -kv[1])[:300])
        n_docs = max(len(doc_terms), 1)
        centroid: dict[str, float] = {}
        for terms in doc_terms:
            vec = tfidf_vector(terms, df, n_docs)
            for k, v in vec.items():
                centroid[k] = centroid.get(k, 0.0) + v / n_docs
        top_centroid = dict(sorted(centroid.items(), key=lambda kv: -kv[1])[:400])

        baselines[register] = {
            "doc_count": len(entries),
            "function_words": fw,
            "scalars": scalars,
            "sent_len_hist": hist_centroid,
            "punct": punct,
            "df": dict(df),
            "n_docs": n_docs,
            "tfidf_centroid": {k: round(v, 6) for k, v in top_centroid.items()},
            "char_ngrams": {k: round(v, 6) for k, v in char_cent.items()},
            "word_bigrams": {k: round(v, 6) for k, v in bigram_cent.items()},
        }
        if progress:
            progress(register, f"baseline from {len(fps)} docs")

    (pack.params_dir / "baselines.json").write_text(json.dumps(baselines))

    # self-calibration: score each corpus doc against its own register baseline
    calib = {}
    for register, entries in by_register.items():
        scores = []
        for e in entries:
            text = extract_text(pack.training_dir / e["path"])
            if text:
                r = score_text(text, baselines[register])
                scores.append(r["composite"])
        if scores:
            m, s = _mean_std(scores)
            calib[register] = {"self_mean": round(m, 1), "self_std": round(s, 1),
                               "self_min": round(min(scores), 1)}
    (pack.params_dir / "calibration.json").write_text(json.dumps(calib, indent=2))
    return baselines


def load_baselines(pack: VoicePack) -> dict:
    p = pack.params_dir / "baselines.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def load_calibration(pack: VoicePack) -> dict:
    p = pack.params_dir / "calibration.json"
    return json.loads(p.read_text()) if p.is_file() else {}


# ---------- scoring ----------

def score_text(text: str, baseline: dict) -> dict:
    """Score one text against one register baseline. Returns components + composite 0-100."""
    fp = fingerprint(text)

    # Burrows' Delta (variance floor prevents blow-ups on small/homogeneous corpora:
    # std is floored at 15% of the mean + a small absolute term)
    zs = []
    for w, (m, s) in baseline["function_words"].items():
        f = fp["function_word_freq"].get(w, 0.0)
        floor = max(s, 0.15 * m + 5e-4)
        zs.append(abs(f - m) / floor)
    delta = sum(zs) / len(zs) if zs else 99.0
    delta_sim = math.exp(-delta / 1.5)  # 0..1, ~0.5 at delta≈1

    # n-grams: char 3-gram + word bigram cosine vs register centroids (avg)
    cn = cosine(char_ngram_profile(text), baseline.get("char_ngrams", {}))
    wb = cosine(word_bigram_profile(text), baseline.get("word_bigrams", {}))
    ngram = 0.6 * cn + 0.4 * wb

    # rhythm: L1 histogram similarity
    bh = baseline.get("sent_len_hist") or []
    dh = fp["sent_len_hist"]
    rhythm = 1 - sum(abs(a - b) for a, b in zip(dh, bh, strict=False)) / 2 if bh else 0.0

    # vocab: tf-idf cosine vs centroid
    vec = tfidf_vector(content_terms(text), baseline.get("df", {}), baseline.get("n_docs", 1))
    vocab = cosine(vec, baseline.get("tfidf_centroid", {}))

    # punctuation: mean per-mark z-similarity
    psims = []
    for p, (m, s) in baseline.get("punct", {}).items():
        f = fp["punct_per_sentence"].get(p, 0.0)
        psims.append(math.exp(-abs(f - m) / max(s, 0.05)))
    punct = sum(psims) / len(psims) if psims else 0.0

    # shape: scalar z-similarity
    ssims = []
    for k, (m, s) in baseline.get("scalars", {}).items():
        f = fp.get(k, 0.0)
        ssims.append(math.exp(-abs(f - m) / max(s, abs(m) * 0.25 + 1e-6)))
    shape = sum(ssims) / len(ssims) if ssims else 0.0

    comps = {"delta": delta_sim, "ngram": ngram, "rhythm": rhythm, "vocab": vocab,
             "punct": punct, "shape": shape}
    composite = 100 * sum(WEIGHTS[k] * v for k, v in comps.items())

    return {
        "fingerprint": fp,
        "burrows_delta": round(delta, 3),
        "components": {k: round(v, 3) for k, v in comps.items()},
        "composite": round(composite, 1),
        "reliable": fp["words"] >= MIN_WORDS_RELIABLE,
    }


def score_against_pack(text: str, pack: VoicePack, register: str | None = None) -> dict:
    """Score text against one register (or all, returning the best + full table)."""
    baselines = load_baselines(pack)
    if not baselines:
        raise RuntimeError(f"no baselines for voice '{pack.name}' — run: revoice learn {pack.name}")
    calib = load_calibration(pack)

    targets = [register] if register else sorted(baselines)
    results = {}
    for reg in targets:
        if reg not in baselines:
            raise RuntimeError(f"register '{reg}' not in voice '{pack.name}' (have: {sorted(baselines)})")
        r = score_text(text, baselines[reg])
        r["calibration"] = calib.get(reg, {})
        results[reg] = r
    best = max(results, key=lambda k: results[k]["composite"])
    return {"best_register": best, "results": results}
