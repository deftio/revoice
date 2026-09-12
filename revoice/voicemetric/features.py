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
PARA_HIST_BINS = [0, 15, 35, 60, 100, 160, 10_000]  # words per paragraph (structural habit)

# --- syntactic proxies: parser-free, and deliberately content-independent ---
# How an author opens sentences is one of the most habitual things they do, and it
# survives topic change completely — which is the property the tf-idf component lacks.
ARTICLES = {"the", "a", "an"}
PRONOUNS = {"i", "you", "he", "she", "it", "we", "they", "his", "her", "its", "our",
            "their", "my", "your", "this", "that", "these", "those", "there"}
CONJUNCTIONS = {"and", "but", "or", "nor", "yet", "so", "for"}
SUBORDINATORS = {"if", "when", "while", "because", "although", "though", "since",
                 "unless", "until", "whereas", "whether", "after", "before", "as"}
PREPOSITIONS = {"of", "in", "to", "on", "at", "by", "with", "from", "into", "over",
                "under", "about", "through", "between", "against", "upon", "among"}
OPENER_CLASSES = ("article", "pronoun", "conjunction", "subordinator", "preposition", "other")

CONTRACTION_RX = re.compile(r"\b\w+(?:n't|'s|'re|'ll|'ve|'d|'m)\b", re.IGNORECASE)
HYPHEN_RX = re.compile(r"\w-\w")

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


def yules_k(counts: Counter) -> float:
    """Yule's K — vocabulary richness that drifts with length far LESS than TTR does.

    Type-token ratio and hapax ratio both fall steadily as a text grows, so a baseline
    built from documents and applied to a paragraph compares two different quantities.
    K is built from the frequency spectrum instead: sum(i^2 * V_i) normalised by N^2.

    This docstring used to say K does not drift with length at all. That was wrong, and
    it was asserted here without a source. Tweedie & Baayen (1998), "How Variable May a
    Constant Be?", measured the length behaviour of the whole family of richness
    constants empirically and found none of them constant — K included. It is markedly
    more stable than TTR, which is why it is the one used here, but "more stable" is the
    honest claim and "length-independent" was not. `bench.length_sensitivity` measures
    the residual drift on the real corpus rather than asking anyone to take it on faith.

    Lower K = richer vocabulary.
    """
    n = sum(counts.values())
    if n < 2:
        return 0.0
    spectrum: Counter = Counter(counts.values())
    m2 = sum((i ** 2) * v for i, v in spectrum.items())
    return 10_000.0 * (m2 - n) / (n * n)


def mtld(words: list[str], threshold: float = 0.72) -> float:
    """Measure of Textual Lexical Diversity — the other length-robust richness measure.

    Walks the token stream accumulating a running type-token ratio; each time the TTR
    falls through `threshold` that is one "factor" and the counter resets. The score is
    tokens per factor, averaged over a forward and a backward pass. Because it counts
    factors rather than dividing types by tokens, it is far flatter in length than raw
    TTR — but see `yules_k` above: flatter is not flat, and the partial trailing factor
    makes short texts the shakiest case. Measured, not assumed: `bench.length_sensitivity`.
    """
    def _pass(seq: list[str]) -> float:
        factors, types, tokens = 0.0, set(), 0
        for w in seq:
            types.add(w)
            tokens += 1
            if tokens and len(types) / tokens <= threshold:
                factors += 1
                types, tokens = set(), 0
        if tokens:  # partial trailing factor, scaled by how far it got
            ttr = len(types) / tokens
            factors += (1 - ttr) / (1 - threshold) if ttr < 1.0 else 0.0
        return len(seq) / factors if factors else float(len(seq))

    if len(words) < 20:
        return 0.0
    return round((_pass(words) + _pass(words[::-1])) / 2, 3)


def _opener_class(word: str) -> str:
    if word in ARTICLES:
        return "article"
    if word in PRONOUNS:
        return "pronoun"
    if word in CONJUNCTIONS:
        return "conjunction"
    if word in SUBORDINATORS:
        return "subordinator"
    if word in PREPOSITIONS:
        return "preposition"
    return "other"


def function_word_bigram_profile(text: str, top: int = 150) -> dict[str, float]:
    """Bigrams in which BOTH words are function words.

    Strictly content-free — 'of the', 'and then', 'it was' say nothing about subject
    matter but a great deal about an author's habitual joinery. The plain word-bigram
    profile mixes these with topical pairs; this one cannot.
    """
    words, _ = tokenize(text)
    fw = set(FUNCTION_WORDS)
    grams = Counter(
        f"{words[i]} {words[i + 1]}"
        for i in range(len(words) - 1)
        if words[i] in fw and words[i + 1] in fw
    )
    total = max(sum(grams.values()), 1)
    return {g: round(c / total, 6) for g, c in grams.most_common(top)}


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

    # --- structural: paragraph shape. Entirely absent before, and one of the most
    # habitual things about a writer (Writeprints calls this the structural family). ---
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    para_lens = [len(re.findall(r"[a-zA-Z']+", p)) for p in paras] or [0]
    sents_per_para = [max(len([x for x in re.split(r"(?<=[.!?])\s+", p) if x.strip()]), 1)
                      for p in paras] or [1]

    # --- syntactic proxies, no parser required ---
    openers: Counter = Counter()
    for sent in sentences:
        first = re.findall(r"[a-zA-Z']+", sent.lower())
        if first:
            openers[_opener_class(first[0])] += 1
    n_open = max(sum(openers.values()), 1)
    subordinator_rate = sum(1 for w in words if w in SUBORDINATORS) / n_words
    conjunction_start = openers["conjunction"] / n_open

    # --- idiosyncratic surface habits ---
    contraction_rate = len(CONTRACTION_RX.findall(text)) / n_words
    hyphen_rate = len(HYPHEN_RX.findall(text)) / n_words

    # --- punctuation *ratios*: how marks are traded off against each other, which is
    # far more personal than any single rate and is scale-free by construction ---
    n_comma = max(punct.get(",", 0), 1)
    semicolon_per_comma = punct.get(";", 0) / n_comma
    dash_per_comma = (punct.get("\u2014", 0) + punct.get("\u2013", 0)) / n_comma
    colon_per_comma = punct.get(":", 0) / n_comma

    return {
        "words": len(words),
        "sentences": len(sentences),
        "mean_sentence_len": round(mean_len, 2),
        "sentence_len_std": round(var**0.5, 2),
        "burstiness": round(var / mean_len, 2) if mean_len else 0.0,
        "sent_len_hist": _hist(sent_lens, SENT_HIST_BINS),
        "word_len_hist": _hist(word_lens, WORD_HIST_BINS),
        "para_len_hist": _hist(para_lens, PARA_HIST_BINS),
        "mean_para_len": round(sum(para_lens) / len(para_lens), 2),
        "mean_sents_per_para": round(sum(sents_per_para) / len(sents_per_para), 2),
        "mean_word_len": round(sum(word_lens) / len(word_lens), 2),
        "type_token_ratio": round(len(counts) / n_words, 4),
        "hapax_ratio": round(hapax / n_words, 4),
        "yules_k": round(yules_k(counts), 2),
        "mtld": mtld(words),
        "adverb_ly_rate": round(ly_rate, 5),
        "nominalization_rate": round(nominal_rate, 5),
        "passive_rate": round(passive_rate, 4),
        "subordinator_rate": round(subordinator_rate, 5),
        "conjunction_start_rate": round(conjunction_start, 4),
        "contraction_rate": round(contraction_rate, 5),
        "hyphen_rate": round(hyphen_rate, 5),
        "semicolon_per_comma": round(semicolon_per_comma, 4),
        "dash_per_comma": round(dash_per_comma, 4),
        "colon_per_comma": round(colon_per_comma, 4),
        "flesch": round(flesch, 1),
        "opener_dist": {k: round(openers[k] / n_open, 4) for k in OPENER_CLASSES},
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
