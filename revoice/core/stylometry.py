"""Deterministic stylometric features. The substrate for voice-match metrics.

All pure descriptive statistics — no LLM, no external NLP deps.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# High-frequency function words — the classic authorship-attribution signal
# (content-independent, hard to fake, stable per author).
FUNCTION_WORDS = (
    "the of and a to in is that it for on with as at by this but not are from or an be have has had "
    "was were will would could should so if then than which who what when where how all any both each "
    "few more most other some such no nor only own same too very can just don now about into over after"
).split()

SENT_HIST_BINS = [0, 5, 10, 15, 20, 25, 30, 40, 60, 10_000]  # words per sentence
WORD_HIST_BINS = [1, 3, 5, 7, 9, 12, 100]  # chars per word

_VOWELS = "aeiouy"


def _syllables(word: str) -> int:
    w = word.lower()
    count, prev = 0, False
    for ch in w:
        v = ch in _VOWELS
        if v and not prev:
            count += 1
        prev = v
    if w.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def tokenize(text: str) -> tuple[list[str], list[str]]:
    """Returns (words, sentences)."""
    words = re.findall(r"[a-zA-Z']+", text.lower())
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n{2,}", text) if s.strip()]
    return words, sentences


def _hist(values: list[float], bins: list[float]) -> list[float]:
    counts = [0] * (len(bins) - 1)
    for v in values:
        for i in range(len(bins) - 1):
            if bins[i] <= v < bins[i + 1]:
                counts[i] += 1
                break
    total = max(sum(counts), 1)
    return [round(c / total, 4) for c in counts]


def fingerprint(text: str) -> dict:
    """Full feature vector for one document."""
    words, sentences = tokenize(text)
    n_words = max(len(words), 1)
    n_sents = max(len(sentences), 1)

    sent_lens = [len(re.findall(r"[a-zA-Z']+", s)) for s in sentences] or [0]
    mean_len = sum(sent_lens) / len(sent_lens)
    var = sum((x - mean_len) ** 2 for x in sent_lens) / len(sent_lens)

    counts = Counter(words)
    hapax = sum(1 for c in counts.values() if c == 1)
    punct = Counter(c for c in text if c in ",;:—–()!?\"'*")
    word_lens = [len(w) for w in words] or [0]

    # morphological / construction proxies
    ly_rate = sum(1 for w in words if w.endswith("ly") and len(w) > 4) / n_words
    nominal_rate = sum(1 for w in words if re.search(r"(tion|ment|ness|ity)s?$", w)) / n_words
    passive_rate = len(re.findall(r"\b(?:was|were|been|being|is|are)\s+\w+ed\b", text.lower())) / n_sents

    syll = sum(_syllables(w) for w in words)
    flesch = 206.835 - 1.015 * (n_words / n_sents) - 84.6 * (syll / n_words)

    return {
        "words": len(words),
        "sentences": len(sentences),
        "mean_sentence_len": round(mean_len, 2),
        "sentence_len_std": round(var**0.5, 2),
        "burstiness": round(var / mean_len, 2) if mean_len else 0.0,
        "sent_len_hist": _hist(sent_lens, SENT_HIST_BINS),
        "word_len_hist": _hist(word_lens, WORD_HIST_BINS),
        "mean_word_len": round(sum(word_lens) / len(word_lens), 2),
        "type_token_ratio": round(len(counts) / n_words, 4),
        "hapax_ratio": round(hapax / n_words, 4),
        "adverb_ly_rate": round(ly_rate, 5),
        "nominalization_rate": round(nominal_rate, 5),
        "passive_rate": round(passive_rate, 4),
        "flesch": round(flesch, 1),
        "function_word_freq": {w: round(counts[w] / n_words, 5) for w in FUNCTION_WORDS},
        "punct_per_sentence": {p: round(c / n_sents, 4) for p, c in punct.items()},
    }


# ---- n-grams (authorship-attribution workhorses; char 3-grams are the strongest single signal) ----

CHAR_NGRAM_N = 3
TOP_CHAR_NGRAMS = 300
TOP_WORD_BIGRAMS = 200


def char_ngram_profile(text: str, n: int = CHAR_NGRAM_N, top: int = TOP_CHAR_NGRAMS) -> dict[str, float]:
    """Normalized frequency of the most common character n-grams (whitespace collapsed)."""
    s = re.sub(r"\s+", " ", text.lower())
    grams = Counter(s[i : i + n] for i in range(len(s) - n + 1))
    total = max(sum(grams.values()), 1)
    return {g: round(c / total, 6) for g, c in grams.most_common(top)}


def word_bigram_profile(text: str, top: int = TOP_WORD_BIGRAMS) -> dict[str, float]:
    words, _ = tokenize(text)
    grams = Counter(" ".join(words[i : i + 2]) for i in range(len(words) - 1))
    total = max(sum(grams.values()), 1)
    return {g: round(c / total, 6) for g, c in grams.most_common(top)}


# ---- tf-idf ----

STOP = set(FUNCTION_WORDS) | set("i you he she we they my your his her its our their me him them us".split())


def content_terms(text: str) -> Counter:
    words, _ = tokenize(text)
    return Counter(w for w in words if w not in STOP and len(w) > 2)


def tfidf_vector(terms: Counter, df: dict[str, int], n_docs: int) -> dict[str, float]:
    total = max(sum(terms.values()), 1)
    vec = {}
    for t, c in terms.items():
        idf = math.log((n_docs + 1) / (df.get(t, 0) + 1)) + 1
        vec[t] = (c / total) * idf
    return vec


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0
