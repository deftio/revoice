"""The voice-metric bench: does our measure of "voice" actually measure voice?

Everything revoice does rests on one classifier decision — *is this passage already in
the target voice?* Minimal-touch, register attribution, the labels the review flywheel
records, and any comparison between a prompted baseline and a fine-tuned model all
inherit that decision's errors. This module measures it. See docs/metrics.md.

No LLM. No new dependencies. Deterministic given a seed.

## The protocol

An authorship-verification trial is (query text, reference author) with a known
same/different label. We build them like this:

  1. **Work-level leave-one-out.** The reference model for a trial NEVER contains the
     work the query came from. This is the topic control, and it is the whole point: if
     the reference for a Twain/adams-diary query is built only from decay-lying and
     dogs-tale, then a score that survives is measuring how Twain writes, not what
     Twain was writing about. Document-level LOO is not enough — two documents from the
     same work share subject matter, so the reference leaks the query's topic.

  2. **Length stratification.** Queries are contiguous word-windows at fixed lengths.
     The instrument's reliability is a function of length, and revoice's real operating
     point (a paragraph-sized span, 25-200 words) is far below the ~1000 words classical
     stylometry is validated at. Reporting one aggregate number hides exactly the regime
     we care about.

  3. **One scoring pass, many scorers.** `score_text` returns six components; a "scorer"
     here is just a weighting over them. So the shipped composite and every ablation are
     evaluated on identical trials, which makes the comparison exact rather than
     approximate.

## The content-control diagnostic

Run the same trials twice — once with work-level LOO (topic controlled) and once with
document-level LOO (reference may contain the query's own work, so topic leaks). The
gap between the two AUCs is the share of apparent performance that is subject matter
rather than authorship. A component whose score collapses under topic control was
never measuring voice. This is the cheap, automatic operationalization of the
STEL-or-Content idea (Wegmann et al. 2022) for our own corpora.

## Reading the output

AUC answers "does it rank correctly". Cllr answers "do the numbers mean anything",
which is the question that matters for a pipeline comparing a score to a threshold.
`tpr@fpr` is the operating point: how much of the author's own writing we keep
untouched, while wrongly leaving at most that fraction of foreign text untouched.
"""

from __future__ import annotations

import math
import random
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from revoice.voicemetric.baseline import (
    COMPONENTS,
    VOICE_COMPONENTS,
    WEIGHTS,
    baseline_from_texts,
    score_text,
)
from revoice.voicemetric.space import AXIS_NAMES, coordinates
from revoice.voicemetric.verify import (
    auc,
    c_at_1,
    cllr_report,
    eer,
    fit_weights,
    tpr_at_fpr,
)

# Query lengths in words. The first three bracket revoice's real span sizes; the last
# three reach up toward the regime classical stylometry was validated in.
DEFAULT_LENGTHS = (50, 100, 200, 400, 800, 1600)

DEFAULT_QUERIES_PER_CELL = 40
DEFAULT_SEED = 17
DEFAULT_MAX_FPR = 0.05

# `<register>-<work>-<part>` — the convention both bundled example packs follow
# (fiction-adams-diary-a-01.md, science-origin-4.md). Files that do not match still
# load; they just get work = the whole stem, which disables topic control for them.
_NAME_RX = re.compile(r"^(?P<register>[a-z]+)-(?P<work>.+?)-(?:[a-z]-)?\d+$")


# ---------- corpus ----------


@dataclass(frozen=True)
class Doc:
    author: str
    work: str
    register: str
    path: str
    text: str

    @property
    def words(self) -> int:
        return len(self.text.split())


def parse_name(stem: str) -> tuple[str, str]:
    """`fiction-adams-diary-a-01` -> ('fiction', 'adams-diary'). Falls back to the stem."""
    m = _NAME_RX.match(stem)
    if not m:
        return "unknown", stem
    return m.group("register"), m.group("work")


def read_text_file(path: Path) -> str | None:
    """Default reader: plain text, and None for anything that is not.

    Binary files are rejected by content — a NUL byte, or decoding that needs too many
    replacement characters — rather than by extension. Sniffing content is the right
    amount of knowledge for this layer: it keeps a stray image out of the corpus without
    the measurement code learning what a .docx is. Callers wanting real document formats
    pass their own `read` (revoice passes its `ingest.extract_text`).
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        # a pure ratio, with no absolute floor: an allowance of "up to N bad bytes"
        # waves through a short binary stub, where N bad bytes are most of the file
        bad = text.count("\ufffd") / max(len(text), 1)
        return None if bad > 0.005 else text


def load_corpus(root: Path, read=read_text_file) -> list[Doc]:
    """Load voice-pack-shaped directories: <root>/<author>/training-data/*.

    Deliberately the same layout as a voice pack, so `examples/voices` benches as-is
    and a purpose-built evaluation corpus (see docs/metrics.md §4.1) drops in beside it.

    `read` is injected so this module never has to know about document formats.
    """
    docs: list[Doc] = []
    root = Path(root)
    for author_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        training = author_dir / "training-data"
        if not training.is_dir():
            continue
        for f in sorted(training.rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            text = read(f)
            if not text or not text.strip():
                continue
            register, work = parse_name(f.stem)
            docs.append(Doc(author_dir.name, work, register, str(f.relative_to(root)), text))
    return docs


def corpus_summary(docs: list[Doc]) -> dict:
    by_author: dict[str, dict] = {}
    for d in docs:
        a = by_author.setdefault(d.author, {"docs": 0, "chars": 0, "works": set(), "registers": {}})
        a["docs"] += 1
        a["chars"] += len(d.text)
        a["works"].add(d.work)
        a["registers"][d.register] = a["registers"].get(d.register, 0) + 1
    return {
        author: {
            "docs": v["docs"],
            "chars": v["chars"],
            "works": sorted(v["works"]),
            "registers": dict(sorted(v["registers"].items())),
        }
        for author, v in sorted(by_author.items())
    }


# ---------- scorers ----------


def _only(component: str) -> dict[str, float]:
    return {c: (1.0 if c == component else 0.0) for c in COMPONENTS}


def _renormalized(drop: tuple[str, ...]) -> dict[str, float]:
    kept = {c: w for c, w in WEIGHTS.items() if c not in drop}
    total = sum(kept.values()) or 1.0
    return {c: kept.get(c, 0.0) / total for c in COMPONENTS}


def uniform(components=COMPONENTS) -> dict[str, float]:
    """Equal weight over the named components, zero elsewhere."""
    w = dict.fromkeys(COMPONENTS, 0.0)
    for c in components:
        w[c] = 1.0 / len(components)
    return w


def default_scorers() -> dict[str, dict[str, float]]:
    """The shipped composite, every component alone, and the ablations worth arguing about."""
    scorers = {"composite": dict(WEIGHTS)}
    for c in COMPONENTS:
        scorers[c] = _only(c)
    scorers["equal-weight"] = uniform()
    scorers["no-vocab"] = _renormalized(("vocab",))
    # the content-independent families only — the hypothesis docs/metrics.md argues for
    scorers["content-free"] = uniform(("delta", "fwbigram", "opener", "syntax", "punct"))
    scorers["ngram+fwbigram"] = uniform(("ngram", "fwbigram"))
    return scorers


def combine(components: dict[str, float], weights: dict[str, float]) -> float:
    """Recombine the six components into one 0-100 score under a given weighting."""
    return 100.0 * sum(weights.get(c, 0.0) * components.get(c, 0.0) for c in COMPONENTS)


# ---------- trials ----------


@dataclass
class Trial:
    ref_author: str
    ref_exclude: str      # the work (or doc path) held out of the reference
    ref_register: str     # genre of the reference author — the grouping key for by_register
    query_author: str
    query_register: str
    length: int
    same: bool
    components: dict[str, float] | None = None


def _window(text: str, n_words: int, rng: random.Random) -> str | None:
    words = text.split()
    if len(words) <= n_words:
        return None
    start = rng.randrange(0, len(words) - n_words)
    return " ".join(words[start : start + n_words])


def _reference_texts(docs: list[Doc], author: str, exclude: str, level: str) -> list[str]:
    """Texts for author's reference model, excluding a work (topic-controlled) or a doc (leaky)."""
    key = (lambda d: d.work) if level == "work" else (lambda d: d.path)
    return [d.text for d in docs if d.author == author and key(d) != exclude]


def run_trials(
    docs: list[Doc],
    lengths=DEFAULT_LENGTHS,
    queries_per_cell: int = DEFAULT_QUERIES_PER_CELL,
    seed: int = DEFAULT_SEED,
    level: str = "work",
    progress=None,
    negatives: str = "any",
) -> list[Trial]:
    """Build and score every trial.

    `level` is 'work' (topic-controlled) or 'doc' (leaky). `negatives` is 'any' — draw
    different-author queries from the whole corpus — or 'same-register', which draws
    them only from authors in the same genre.

    On a multi-genre corpus 'any' is the easy setting and will flatter the measure:
    most negative pairs then differ in genre as well as authorship, and separating a
    cookery manual from an adventure novel is not authorship attribution.
    'same-register' is the contrast that matters.
    """
    rng = random.Random(seed)
    authors = sorted({d.author for d in docs})
    if len(authors) < 2:
        raise RuntimeError(
            f"bench needs at least 2 authors to form different-author trials (found: {authors})"
        )

    key = (lambda d: d.work) if level == "work" else (lambda d: d.path)
    trials: list[Trial] = []

    registers_of = {a: {d.register for d in docs if d.author == a} for a in authors}

    for author in authors:
        own = [d for d in docs if d.author == author]
        if negatives == "same-register":
            others = [d for d in docs
                      if d.author != author and (registers_of[d.author] & registers_of[author])]
        else:
            others = [d for d in docs if d.author != author]
        if not others:
            continue  # no same-genre rival to contrast against
        for exclude in sorted({key(d) for d in own}):
            ref_texts = _reference_texts(docs, author, exclude, level)
            if len(ref_texts) < 2:
                continue  # a reference model needs at least two documents to have a variance
            held_out = [d for d in own if key(d) == exclude]
            baseline = baseline_from_texts(ref_texts)
            if progress:
                progress(f"{author}/{exclude}", f"reference from {len(ref_texts)} docs")

            for length in lengths:
                pos = [d for d in held_out if d.words > length]
                neg = [d for d in others if d.words > length]
                if not pos or not neg:
                    continue
                for source, same in ((pos, True), (neg, False)):
                    for _ in range(queries_per_cell):
                        doc = rng.choice(source)
                        # doc.words > length was checked above, so a window always exists
                        text = _window(doc.text, length, rng)
                        trials.append(
                            Trial(
                                ref_author=author,
                                ref_exclude=exclude,
                                ref_register=held_out[0].register,
                                query_author=doc.author,
                                query_register=doc.register,
                                length=length,
                                same=same,
                                components=score_text(text, baseline)["components"],
                            )
                        )
    return trials


# ---------- evaluation ----------


def _split(trials: list[Trial], weights: dict[str, float]) -> tuple[list[float], list[float]]:
    target = [combine(t.components, weights) for t in trials if t.same and t.components]
    nontarget = [combine(t.components, weights) for t in trials if not t.same and t.components]
    return target, nontarget


def _metrics(target: list[float], nontarget: list[float], max_fpr: float) -> dict:
    """All verification measures for one (scorer, length) cell."""
    if not target or not nontarget:
        return {"auc": float("nan"), "eer": float("nan"), "tpr_at_fpr": float("nan"),
                "threshold": None, "cllr": float("nan"), "cllr_min": float("nan"),
                "cllr_cal": float("nan"), "n_same": len(target), "n_different": len(nontarget)}
    tpr, threshold = tpr_at_fpr(target, nontarget, max_fpr)
    out = {
        "auc": round(auc(target, nontarget), 4),
        "eer": round(eer(target, nontarget), 4),
        "tpr_at_fpr": round(tpr, 4) if tpr == tpr else tpr,
        "threshold": round(threshold, 2) if threshold not in (float("inf"), float("nan")) else None,
        "n_same": len(target),
        "n_different": len(nontarget),
    }
    out.update(cllr_report(target, nontarget))
    out["decision"] = _decision_quality(target, nontarget)
    return out


def _decision_quality(target: list[float], nontarget: list[float]) -> dict:
    """Does letting the system abstain make its decisions better? c@1 answers that.

    AUC and EER both grade a ranker. This engine is not asked to rank, it is asked to
    decide — and its most common correct answer is "these overlap, I cannot call it".
    c@1 is the only measure here that can score that answer as anything but a coin flip.

    The sweep widens an abstention band around the decision threshold and reports the
    band that scores best. If the best band is 0, abstaining never helps and the system
    may as well always answer; if a wide band wins, the scores carry real information
    about their own reliability and we should be using it. `abstain_rate` is the price.

    The threshold maximises accuracy on these same trials, so it is an oracle and these
    figures are an upper bound — the same optimism `tpr_at_fpr` already carries, kept
    consistent rather than quietly mixed.
    """
    scores = sorted(set(target + nontarget))
    if len(scores) < 2:
        return {"threshold": None, "c_at_1": float("nan"), "accuracy": float("nan"),
                "band": 0.0, "abstain_rate": 0.0}
    cuts = [(a + b) / 2 for a, b in zip(scores, scores[1:], strict=False)]
    threshold = max(cuts, key=lambda c: c_at_1(target, nontarget, c)["accuracy"])

    all_scores = target + nontarget
    mean = sum(all_scores) / len(all_scores)
    sd = (sum((s - mean) ** 2 for s in all_scores) / len(all_scores)) ** 0.5
    best = max((c_at_1(target, nontarget, threshold, f * sd) for f in (0.0, 0.1, 0.25, 0.5, 1.0)),
               key=lambda r: r["c_at_1"])
    n = len(all_scores)
    return {
        "threshold": round(threshold, 3),
        "c_at_1": best["c_at_1"],
        "accuracy": c_at_1(target, nontarget, threshold)["accuracy"],
        "band": round(best["band"], 3),
        "abstain_rate": round(best["abstained"] / n, 4),
    }


def _macro(by_length: dict, keys=("auc", "eer", "tpr_at_fpr", "cllr", "cllr_min", "cllr_cal")) -> dict:
    """Average each measure across the lengths that produced trials.

    Macro-averaging, not pooling. These scores are length-dependent — that is the
    finding, not an incidental — so concatenating trials of different lengths mixes
    distributions with different means and produces an aggregate that can sit below
    every one of its parts. The per-length numbers are the real result; this is their
    honest summary. (The pooled figures are kept in the JSON, marked, for reference.)
    """
    out = {}
    for k in keys:
        vals = [v[k] for v in by_length.values() if v.get(k) == v.get(k) and v.get(k) is not None]
        out[k] = round(sum(vals) / len(vals), 4) if vals else float("nan")
    return out


def evaluate(trials: list[Trial], scorers: dict[str, dict[str, float]] | None = None,
             lengths=DEFAULT_LENGTHS, max_fpr: float = DEFAULT_MAX_FPR) -> dict:
    """Per-length verification measures for every scorer, plus their macro average."""
    scorers = scorers or default_scorers()
    coverage = {}
    for length in lengths:
        subset = [t for t in trials if t.length == length]
        coverage[length] = {"n_same": sum(1 for t in subset if t.same),
                            "n_different": sum(1 for t in subset if not t.same)}

    out: dict = {
        "scorers": {},
        "lengths": list(lengths),
        "coverage": coverage,
        "n_trials": len(trials),
        "n_same": sum(1 for t in trials if t.same),
        "n_different": sum(1 for t in trials if not t.same),
        "max_fpr": max_fpr,
    }

    for name, weights in scorers.items():
        by_length = {}
        for length in lengths:
            subset = [t for t in trials if t.length == length]
            by_length[length] = _metrics(*_split(subset, weights), max_fpr)
        entry = {"by_length": by_length, "macro": _macro(by_length)}
        # pooled across lengths: retained for reference, but length-mixed (see _macro)
        entry["pooled_length_mixed"] = _metrics(*_split(trials, weights), max_fpr)
        entry["auc"] = entry["macro"]["auc"]
        out["scorers"][name] = entry
    return out


def fit_scorer(trials: list[Trial], lengths=DEFAULT_LENGTHS) -> dict[str, float]:
    """Fit component weights on these trials. Returns a weight dict summing to 1.

    Fits over VOICE_COMPONENTS only — `vocab` is held out on purpose. It is the
    strongest single component on every corpus we have and it is measuring subject
    matter; an unconstrained fitter hands it half the weight and reports an AUC that
    will not survive the author changing topic.

    Fitting is done on standardized component vectors pooled across lengths, which is
    fine here (unlike reporting) because we want one weighting that works everywhere
    rather than a per-length answer.
    """
    tar = [[t.components.get(c, 0.0) for c in VOICE_COMPONENTS]
           for t in trials if t.same and t.components and t.length in lengths]
    non = [[t.components.get(c, 0.0) for c in VOICE_COMPONENTS]
           for t in trials if not t.same and t.components and t.length in lengths]
    w = fit_weights(tar, non)
    if not w:
        return dict(WEIGHTS)
    fitted = dict.fromkeys(COMPONENTS, 0.0)
    fitted.update(dict(zip(VOICE_COMPONENTS, w, strict=True)))
    return fitted


def split_trials(trials: list[Trial], fold: int = 2):
    """Deterministic split for honest fit/evaluate separation: fit on one half of the
    reference models, evaluate on the other. Splitting by REFERENCE rather than by
    trial keeps a fitted weighting from being scored on the same baselines it saw."""
    keys = sorted({(t.ref_author, t.ref_exclude) for t in trials})
    held = {k for i, k in enumerate(keys) if i % fold == 0}
    fit = [t for t in trials if (t.ref_author, t.ref_exclude) not in held]
    ev = [t for t in trials if (t.ref_author, t.ref_exclude) in held]
    return fit, ev


def by_register(trials: list[Trial], weights: dict[str, float] | None = None,
                max_fpr: float = DEFAULT_MAX_FPR) -> dict:
    """Per-genre discrimination for one weighting.

    Authorship is not equally hard everywhere: comic writers have loud personal voices,
    while four Victorian naturalists writing scientific argument share a house style.
    A single aggregate hides that, and the per-genre spread is the more useful answer
    for anyone deciding whether the measure is good enough for THEIR kind of writing.
    """
    weights = weights or dict(WEIGHTS)
    registers = sorted({t.ref_register for t in trials})
    out = {}
    for reg in registers:
        subset = [t for t in trials if t.ref_register == reg]
        target, nontarget = _split(subset, weights)
        m = _metrics(target, nontarget, max_fpr)
        out[reg] = {"auc": m["auc"], "eer": m["eer"], "tpr_at_fpr": m["tpr_at_fpr"],
                    "n_same": m["n_same"], "n_different": m["n_different"],
                    "authors": len({t.ref_author for t in subset})}
    return out


def content_control(controlled: dict, leaky: dict) -> dict:
    """AUC lost when the reference can no longer see the query's own work.

    A large drop means the score was reading subject matter. Reported per scorer.
    """
    out = {}
    for name, strict in controlled["scorers"].items():
        loose = leaky["scorers"].get(name)
        if not loose:
            continue
        a_strict, a_loose = strict["macro"]["auc"], loose["macro"]["auc"]
        out[name] = {
            "auc_topic_controlled": a_strict,
            "auc_topic_leaked": a_loose,
            "topic_contribution": round(a_loose - a_strict, 4)
            if a_strict == a_strict and a_loose == a_loose else float("nan"),
        }
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx > 1e-12 and dy > 1e-12 else float("nan")


def _truncate(words: list[str], text: str, n: int, cut: str) -> str:
    """Take roughly `n` words, the way the caller's real pipeline would take them."""
    if cut == "words":
        return " ".join(words[:n])
    out, count = [], 0
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        out.append(para)
        count += len(para.split())
        if count >= n:
            break
    return "\n\n".join(out)


def length_sensitivity(docs: list[Doc], lengths=DEFAULT_LENGTHS,
                       min_words: int = 0, cut: str = "words") -> dict:
    """How much does each axis move when you change only HOW MUCH text you feed it?

    This exists because of a claim this package used to make about itself. `yules_k`
    asserted, with no source, that Yule's K "does NOT drift with text length". Tweedie &
    Baayen (1998) measured the whole family of richness constants and found none of them
    constant. The docstring is fixed; this function is the part that stops us doing it
    again, by measuring the residual drift instead of arguing about it.

    Method: take one document, truncate it to each length in the grid, and read the
    axes off each truncation. Everything except the amount of text is held fixed — same
    author, same work, same topic, same register — so any movement across the row is a
    length artifact and nothing else. Per-axis Pearson r against log(words), averaged
    over documents.

    Two numbers per axis:

      r      within-document correlation with log length. |r| near 1 means the axis is
             substantially reporting how much text it was given.
      drift  the shift from the shortest length to the longest, in units of the axis's
             own across-document spread. This is the one that matters operationally:
             drift of 1.0 means changing the sample length moves the axis as far as
             changing the author does, and any comparison across unequal lengths is
             then measuring the inequality.

    `cut` picks which of the two regimes to measure, and they are not the same:

      "words"       take the first n words, splitting paragraphs wherever n lands. This
                    is what `bench._window` does to build trials and what revoice does
                    to a span, so it is the regime the published AUC figures live in.
      "paragraphs"  take whole paragraphs until n is reached — what `space.windows` does
                    for the page and the report.

    Run both. The first time this was run, the difference exposed something nobody had
    claimed and nobody had checked: under "words" the paragraph-shape axes are pure
    length readings, because joining a span's words on spaces leaves exactly one
    paragraph. They are not wrong on the page, where windows are cut on paragraph
    boundaries; they are dead in the bench, where they are not.

    `min_words` skips documents too short to fill the grid; leaving it at 0 includes
    every document at every length it can actually reach.
    """
    if cut not in ("words", "paragraphs"):
        raise ValueError("cut must be 'words' or 'paragraphs'")
    grid = sorted(lengths)
    logs = [math.log(n) for n in grid]

    per_axis_r: dict[str, list[float]] = {a: [] for a in AXIS_NAMES}
    rows: dict[str, list[list[float]]] = {a: [] for a in AXIS_NAMES}
    used = 0
    for doc in docs:
        words = doc.text.split()
        if len(words) < max(min_words, grid[0]):
            continue
        reachable = [n for n in grid if n <= len(words)]
        if len(reachable) < 2:
            continue
        used += 1
        coords = [coordinates(_truncate(words, doc.text, n, cut)) for n in reachable]
        xs = logs[:len(reachable)]
        for a in AXIS_NAMES:
            ys = [c[a] for c in coords]
            r = _pearson(xs, ys)
            # A constant axis has no correlation with length, which is the BEST possible
            # result here and must not be reported as unmeasurable. `_pearson` returns
            # nan when its input does not vary; for this diagnostic that case means the
            # axis did not move when the length did, so it is 0.0.
            if r != r and max(ys) == min(ys):
                r = 0.0
            if r == r:
                per_axis_r[a].append(r)
            if len(reachable) == len(grid):
                rows[a].append(ys)

    axes = {}
    for a in AXIS_NAMES:
        rs = per_axis_r[a]
        full = rows[a]
        spread = 0.0
        drift = float("nan")
        if full:
            # spread ACROSS documents at the longest length: the scale a real difference
            # between two writers would be measured on
            longest = [row[-1] for row in full]
            m = sum(longest) / len(longest)
            spread = (sum((v - m) ** 2 for v in longest) / len(longest)) ** 0.5
            shifts = [row[-1] - row[0] for row in full]
            mean_shift = sum(shifts) / len(shifts)
            drift = mean_shift / spread if spread > 1e-12 else float("nan")
        axes[a] = {
            "r": round(sum(rs) / len(rs), 4) if rs else float("nan"),
            "drift": round(drift, 3) if drift == drift else drift,
            "n_docs": len(rs),
        }

    ranked = sorted(AXIS_NAMES, key=lambda a: -abs(axes[a]["r"]) if axes[a]["r"] == axes[a]["r"] else 0)
    return {"lengths": grid, "n_docs": used, "cut": cut, "axes": axes, "worst_first": ranked}


def render_length_sensitivity(result: dict) -> str:
    """The drift table, worst axis first."""
    out = [f"length sensitivity — {result['n_docs']} docs over "
           f"{result['lengths'][0]}..{result['lengths'][-1]} words, cut on "
           f"{result.get('cut', 'words')}", ""]
    out.append(f"  {'axis':<24}{'r(log n)':>10}{'drift (sd)':>13}")
    for a in result["worst_first"]:
        e = result["axes"][a]
        r, d = e["r"], e["drift"]
        flag = "  <-- length-dominated" if r == r and abs(r) >= 0.8 else ""
        out.append(f"  {a:<24}{r:>10.3f}{(f'{d:+.2f}' if d == d else 'n/a'):>13}{flag}")
    out.append("")
    out.append("  r is within-document: the same text, truncated. Anything it moves is length.")
    return "\n".join(out)


def interval_coverage(docs: list[Doc], population, levels=(0.5, 0.8, 0.9, 0.95),
                      replicates: int = 400, min_windows: int = 6, seed: int = 11) -> dict:
    """Does a 90% interval actually contain the answer 90% of the time?

    Every report this package emits leads with an interval, and §1e argues the interval
    is the honest part — the thing that stops a bare number inviting a decision it cannot
    support. That argument is worth exactly as much as the interval's coverage, and
    coverage had never been measured.

    Two tests, because the obvious one is unfair and it took a wrong answer to notice.

    **`null_difference` (primary).** Deal a document's windows alternately into halves A
    and B, so both span the whole document rather than its two ends. A and B are the same
    author, same work, same topic, same register — the true difference between them is
    zero, by construction. Bootstrap that difference the way `transfer.style_delta` does
    (resample each half independently, subtract, take percentiles) and ask how often the
    interval contains zero. A calibrated 90% interval does so 90% of the time. This test
    has no bias to correct: it is a real null, and it validates the exact construction the
    `moved` verdict depends on.

    **`half_vs_half` (secondary).** Build the interval from A, take the point estimate
    from B, ask whether B's point lands inside A's band. This is the intuitive test and
    it is *systematically pessimistic*: A's interval carries A's sampling noise, while
    B's point carries its own, so the quantity being tested has √2 times the spread the
    interval was built for. A perfectly calibrated 90% interval scores 0.755 here, not
    0.90. `expected` records that benchmark next to the observed value, because the raw
    number looks like a damning result and is not one.

    Regions are fitted per author with the document's own work held out, matching the
    bench's topic control — otherwise the region has already read what it is scoring.
    """
    from revoice.voicemetric.space import (
        VoiceRegion,
        _percentile,
        axis_similarity,
        report_from_windows,
        windows,
    )

    def overall(zs, region):
        zbar = {a: sum(z[a] for z in zs) / len(zs) for a in AXIS_NAMES}
        sims = axis_similarity(zbar, region)
        return 100.0 * sum(sims.values()) / len(AXIS_NAMES)

    by_author: dict[str, list[Doc]] = {}
    for d in docs:
        by_author.setdefault(d.author, []).append(d)

    null_hits = {lv: 0 for lv in levels}
    hv_hits = {lv: 0 for lv in levels}
    widths: list[float] = []
    null_widths: list[float] = []
    misses_low = misses_high = tested = 0
    rng = random.Random(seed)

    for author, own in by_author.items():
        if len({d.work for d in own}) < 2:
            continue                      # nothing to hold out
        for doc in own:
            ws = windows(doc.text)
            if len(ws) < min_windows:
                continue
            ref = [d.text for d in own if d.work != doc.work]
            if len(ref) < 2:
                continue
            region = VoiceRegion.fit(author, ref, population)
            zs = [population.standardize(w) for w in ws]
            a, b = zs[0::2], zs[1::2]
            if len(a) < 3 or len(b) < 3:
                continue

            tested += 1
            # One seed per document, shared across levels, so the bands nest properly:
            # the 95% interval contains the 90% one instead of being a separate draw.
            doc_seed = rng.randrange(10 ** 6)

            # --- primary: bootstrap the difference, which is truly zero ---
            nrng = random.Random(doc_seed)
            diffs = []
            for _ in range(replicates):
                pa = [a[nrng.randrange(len(a))] for _ in range(len(a))]
                pb = [b[nrng.randrange(len(b))] for _ in range(len(b))]
                diffs.append(overall(pa, region) - overall(pb, region))
            diffs.sort()
            for lv in levels:
                lo = _percentile(diffs, (1 - lv) / 2)
                hi = _percentile(diffs, 1 - (1 - lv) / 2)
                null_hits[lv] += lo <= 0.0 <= hi
                if lv == 0.9:
                    null_widths.append(hi - lo)

            # --- secondary: A's interval against B's point ---
            truth = overall(b, region)
            for lv in levels:
                r = report_from_windows(a, region, replicates, lv, doc_seed)
                covered = r["low"] <= truth <= r["high"]
                hv_hits[lv] += covered
                if lv == 0.9:
                    widths.append(r["high"] - r["low"])
                    if not covered:
                        misses_low += truth < r["low"]
                        misses_high += truth > r["high"]

    def _med(xs):
        return round(sorted(xs)[len(xs) // 2], 2) if xs else float("nan")

    def _rate(h):
        return round(h / tested, 4) if tested else float("nan")

    return {
        "n": tested,
        "null_difference": {lv: {"nominal": lv, "covered": _rate(null_hits[lv])}
                            for lv in levels},
        "half_vs_half": {lv: {"nominal": lv, "covered": _rate(hv_hits[lv]),
                              "expected": round(_normal_pair_expectation(lv), 4)}
                         for lv in levels},
        "median_width_at_90": _med(widths),
        "median_null_width_at_90": _med(null_widths),
        "misses_low": misses_low,
        "misses_high": misses_high,
    }


def _normal_pair_expectation(level: float) -> float:
    """What a PERFECTLY calibrated interval scores on the half-vs-half test.

    The tested quantity is a difference of two independent estimates, so it has √2 times
    the spread the interval was built to cover. Under normality that turns a nominal 0.90
    into 0.755. Without this benchmark printed alongside, the raw coverage reads as a
    damning result when most of the shortfall is the test's own geometry.
    """
    from statistics import NormalDist

    z = NormalDist().inv_cdf(0.5 + level / 2)
    return 2 * NormalDist().cdf(z / math.sqrt(2)) - 1


def render_interval_coverage(result: dict) -> str:
    """Nominal vs actual coverage. The diagonal is the goal."""
    out = [f"interval coverage — {result['n']} documents, split into halves", ""]
    out.append("  NULL DIFFERENCE (primary) — two halves of one document differ by zero;")
    out.append("  how often does the interval on that difference contain zero?")
    out.append(f"    {'nominal':>9}{'actual':>9}{'error':>9}")
    for _lv, e in sorted(result["null_difference"].items()):
        err = e["covered"] - e["nominal"]
        flag = ("  <-- too narrow: overconfident" if err < -0.03 else
                "  <-- too wide: power left unused" if err > 0.03 else "")
        out.append(f"    {e['nominal']:>9.2f}{e['covered']:>9.3f}{err:>+9.3f}{flag}")
    out.append("")
    out.append("  HALF VS HALF (secondary) — pessimistic by \u221a2; 'expected' is what a")
    out.append("  perfectly calibrated interval would score on this test, not the nominal.")
    out.append(f"    {'nominal':>9}{'actual':>9}{'expected':>10}{'error':>9}")
    for _lv, e in sorted(result["half_vs_half"].items()):
        err = e["covered"] - e["expected"]
        out.append(f"    {e['nominal']:>9.2f}{e['covered']:>9.3f}"
                   f"{e['expected']:>10.3f}{err:>+9.3f}")
    out.append("")
    out.append(f"  median 90% width: {result['median_width_at_90']} points "
               f"(on the difference: {result['median_null_width_at_90']})")
    out.append(f"  misses below the band: {result['misses_low']}   above: {result['misses_high']}")
    return "\n".join(out)


def verdict(result: dict, max_fpr: float = DEFAULT_MAX_FPR) -> list[str]:
    """Plain-language findings. The bench should answer the question, not just tabulate."""
    notes: list[str] = []
    scorers = result.get("scorers", {})
    if not scorers:
        return ["no trials scored"]

    def macro(name: str, key: str):
        return scorers.get(name, {}).get("macro", {}).get(key)

    # coverage: a length with no trials is a corpus limitation, not a result
    empty = [L for L, c in result.get("coverage", {}).items()
             if not c["n_same"] or not c["n_different"]]
    if empty:
        notes.append(
            f"no trials at {', '.join(str(L) + 'w' for L in empty)} — the corpus has no "
            "documents long enough on both sides. Those lengths are untested, not passing."
        )

    ranked = sorted(((n, macro(n, "auc")) for n in scorers if macro(n, "auc") == macro(n, "auc")),
                    key=lambda kv: -kv[1])
    comp_auc = macro("composite", "auc")
    if ranked and comp_auc == comp_auc:
        best_name, best_auc = ranked[0]
        if best_name != "composite" and best_auc - comp_auc > 0.01:
            notes.append(
                f"the shipped composite (AUC {comp_auc:.3f}) is beaten by '{best_name}' "
                f"(AUC {best_auc:.3f}, +{best_auc - comp_auc:.3f}) — the weights are not fit to data"
            )

    near_chance = [n for n, a in ranked if a < 0.6]
    if near_chance:
        notes.append(
            f"at or near chance (AUC < 0.60): {', '.join(near_chance)}"
            + (" — including the shipped composite" if "composite" in near_chance else "")
        )

    for name, entry in scorers.items():
        aucs = [v["auc"] for v in entry["by_length"].values() if v["auc"] == v["auc"]]
        if len(aucs) >= 3 and aucs[-1] < max(aucs) - 0.05:
            notes.append(
                f"'{name}' is non-monotonic in length (best {max(aucs):.3f}, "
                f"longest-query {aucs[-1]:.3f}) — more evidence should never hurt"
            )

    cllr = macro("composite", "cllr")
    if cllr == cllr:
        if cllr >= 0.99:
            notes.append(
                f"composite cllr {cllr:.3f} — at 1.0 a system is worth exactly as much as "
                "always answering 'don't know'. As delivered, it carries almost no information."
            )
        cal = macro("composite", "cllr_cal")
        if cal == cal and cal > 0.1:
            notes.append(f"composite loses {cal:.3f} bits to miscalibration alone "
                         f"(floor {macro('composite', 'cllr_min'):.3f}) — it ranks better than it means")

    tpr = macro("composite", "tpr_at_fpr")
    if tpr == tpr:
        notes.append(
            f"OPERATING POINT: at a {max_fpr:.0%} false-positive rate the composite keeps "
            f"{tpr:.0%} of the author's own text untouched. Minimal-touch needs this high; "
            "this is the number to move."
        )

    cc = result.get("content_control", {})
    leaks = sorted(((n, v["topic_contribution"]) for n, v in cc.items()
                    if v["topic_contribution"] == v["topic_contribution"]), key=lambda kv: -kv[1])
    for name, delta in leaks[:3]:
        if delta > 0.05:
            notes.append(
                f"'{name}' loses {delta:.3f} AUC under topic control — that share of its "
                "apparent performance was subject matter, not voice"
            )
    return notes


def bench(root: Path, lengths=DEFAULT_LENGTHS, queries_per_cell: int = DEFAULT_QUERIES_PER_CELL,
          seed: int = DEFAULT_SEED, max_fpr: float = DEFAULT_MAX_FPR,
          skip_content_control: bool = False, progress=None, fit: bool = False,
          negatives: str = "any") -> dict:
    """Full bench run. Returns a JSON-serializable report."""
    docs = load_corpus(root)
    if not docs:
        raise RuntimeError(f"no documents found under {root} (expected <author>/training-data/*)")

    trials = run_trials(docs, lengths, queries_per_cell, seed, "work", progress, negatives)
    if not trials:
        raise RuntimeError(
            f"no trials built from {root} — need >=2 authors with >=2 works each"
            + (" sharing a register (negatives='same-register')" if negatives == "same-register" else ""))
    scorers = None
    if fit:
        # Fit on one half of the reference models and score on the other, so the
        # reported AUC for "fitted" is not the AUC of a weighting that already saw
        # these baselines. Anything else would be marking our own homework.
        fit_half, _ = split_trials(trials)
        fitted = fit_scorer(fit_half, lengths)
        scorers = default_scorers()
        scorers["fitted"] = fitted
    result = evaluate(trials, scorers, lengths, max_fpr)
    if fit:
        _, eval_half = split_trials(trials)
        held = evaluate(eval_half, {"fitted": scorers["fitted"]}, lengths, max_fpr)
        result["fitted_weights"] = {k: round(v, 4) for k, v in scorers["fitted"].items()}
        result["fitted_heldout"] = held["scorers"]["fitted"]["macro"]
    result["corpus"] = corpus_summary(docs)
    result["protocol"] = {
        "leave_one_out": "work",
        "negatives": negatives,
        "lengths": list(lengths),
        "queries_per_cell": queries_per_cell,
        "seed": seed,
        "max_fpr": max_fpr,
    }

    if not skip_content_control:
        leaky_trials = run_trials(docs, lengths, queries_per_cell, seed, "doc", progress, negatives)
        result["content_control"] = content_control(
            result, evaluate(leaky_trials, None, lengths, max_fpr)
        )

    result["by_register"] = by_register(trials, scorers["fitted"] if fit else None, max_fpr)
    result["verdict"] = verdict(result, max_fpr)
    return result


# ---------- rendering ----------


def _fmt(x, width: int = 8, places: int = 3) -> str:
    if x is None or x != x:
        return "—".rjust(width)
    return f"{x:>{width}.{places}f}"


def render(result: dict) -> str:
    """Human-readable bench report."""
    lines: list[str] = []
    lines.append("CORPUS")
    for author, v in result.get("corpus", {}).items():
        regs = " ".join(f"{r}({n})" for r, n in v["registers"].items())
        lines.append(f"  {author:<12} {v['docs']:>3} docs  {v['chars']:>8,} chars  "
                     f"{len(v['works'])} works: {', '.join(v['works'])}")
        lines.append(f"  {'':<12} registers: {regs}")

    p = result.get("protocol", {})
    lines.append("")
    lines.append(f"PROTOCOL  {p.get('leave_one_out')}-level leave-one-out · "
                 f"{p.get('negatives', 'any')} negatives · "
                 f"{len(p.get('lengths', []))} lengths · {p.get('queries_per_cell')} queries/cell · "
                 f"seed {p.get('seed')}")
    lines.append(f"          {result['n_trials']:,} trials "
                 f"({result['n_same']:,} same-author / {result['n_different']:,} different-author)")
    cov = result.get("coverage", {})
    empty = [L for L, c in cov.items() if not c["n_same"] or not c["n_different"]]
    if empty:
        lines.append(f"          NO TRIALS at {', '.join(str(L) + 'w' for L in empty)} "
                     "— corpus lacks long enough documents on both sides")

    lengths = result.get("lengths", [])
    lines.append("")
    lines.append("DISCRIMINATION — AUC by query length (0.5 = chance)")
    lines.append("  " + "scorer".ljust(24) + "".join(f"{str(L) + 'w':>8}" for L in lengths)
                 + f"{'macro':>9}")
    lines.append("  " + "-" * (24 + 8 * len(lengths) + 9))
    for name, s_ in sorted(result["scorers"].items(),
                           key=lambda kv: -(kv[1]["macro"]["auc"]
                                            if kv[1]["macro"]["auc"] == kv[1]["macro"]["auc"] else -1)):
        row = "".join(_fmt(s_["by_length"].get(L, {}).get("auc")) for L in lengths)
        lines.append("  " + name.ljust(24) + row + _fmt(s_["macro"]["auc"], 9))

    lines.append("")
    lines.append("CALIBRATION & OPERATING POINT (macro-averaged over lengths, not pooled)")
    lines.append("  " + "scorer".ljust(24) + f"{'cllr':>8}{'cllr_min':>10}{'cllr_cal':>10}"
                 f"{'eer':>8}{'tpr@fpr':>9}")
    lines.append("  " + "-" * 69)
    for name, s_ in result["scorers"].items():
        m = s_["macro"]
        lines.append("  " + name.ljust(24) + _fmt(m.get("cllr")) + _fmt(m.get("cllr_min"), 10)
                     + _fmt(m.get("cllr_cal"), 10) + _fmt(m.get("eer")) + _fmt(m.get("tpr_at_fpr"), 9))
    lines.append("  (cllr 1.0 = no more useful than always answering \"don't know\"; 0 = perfect)")

    cc = result.get("content_control")
    if cc:
        lines.append("")
        lines.append("CONTENT CONTROL — AUC lost when the reference cannot see the query's own work")
        lines.append("  " + "scorer".ljust(24) + f"{'controlled':>12}{'leaked':>9}{'topic share':>13}")
        lines.append("  " + "-" * 58)
        ordered = sorted(cc.items(),
                         key=lambda kv: -(kv[1]["topic_contribution"]
                                          if kv[1]["topic_contribution"] == kv[1]["topic_contribution"]
                                          else -1))
        for name, v in ordered:
            lines.append("  " + name.ljust(24) + _fmt(v["auc_topic_controlled"], 12)
                         + _fmt(v["auc_topic_leaked"], 9) + _fmt(v["topic_contribution"], 13))

    br = result.get("by_register")
    if br and len(br) > 1:
        lines.append("")
        lines.append("BY GENRE — composite AUC within each group (same-genre rivals)")
        lines.append("  " + "genre".ljust(14) + f"{'authors':>8}{'trials':>9}{'AUC':>8}{'EER':>8}{'tpr@fpr':>9}")
        lines.append("  " + "-" * 56)
        for reg, v in sorted(br.items(), key=lambda kv: -(kv[1]["auc"] if kv[1]["auc"] == kv[1]["auc"] else -1)):
            lines.append("  " + reg.ljust(14) + f"{v['authors']:>8}"
                         + f"{v['n_same'] + v['n_different']:>9}"
                         + _fmt(v["auc"]) + _fmt(v["eer"]) + _fmt(v["tpr_at_fpr"], 9))

    fw = result.get("fitted_weights")
    if fw:
        lines.append("")
        lines.append("FITTED WEIGHTS (logistic, L2, fitted on half the reference models)")
        ranked = sorted(fw.items(), key=lambda kv: -kv[1])
        for name, weight in ranked:
            bar = "█" * int(round(weight * 60))
            lines.append(f"  {name.ljust(12)}{weight:>7.3f}  {bar}")
        ho = result.get("fitted_heldout") or {}
        if ho:
            lines.append(f"  held-out macro AUC {ho.get('auc')}  EER {ho.get('eer')}  "
                         f"cllr {ho.get('cllr')}")

    v = result.get("verdict") or []
    if v:
        lines.append("")
        lines.append("VERDICT")
        for note in v:
            lines.append(f"  · {note}")
    return "\n".join(lines)


def summarize_lengths(result: dict, scorer: str = "composite") -> dict:
    """Mean/spread of a scorer's AUC across lengths — used by tests and regression gates."""
    s = result["scorers"][scorer]
    aucs = [v["auc"] for v in s["by_length"].values() if v["auc"] == v["auc"]]
    if not aucs:
        return {"n": 0}
    return {
        "n": len(aucs),
        "min": round(min(aucs), 4),
        "max": round(max(aucs), 4),
        "mean": round(statistics.mean(aucs), 4),
        "monotone": all(b >= a - 0.02 for a, b in zip(aucs, aucs[1:], strict=False)),
    }
