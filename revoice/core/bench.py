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

import random
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from revoice.core.ingest import extract_text
from revoice.core.metrics import WEIGHTS, baseline_from_texts, score_text
from revoice.core.verify import auc, cllr_report, eer, tpr_at_fpr

# Query lengths in words. The first three bracket revoice's real span sizes; the last
# three reach up toward the regime classical stylometry was validated in.
DEFAULT_LENGTHS = (50, 100, 200, 400, 800, 1600)

DEFAULT_QUERIES_PER_CELL = 40
DEFAULT_SEED = 17
DEFAULT_MAX_FPR = 0.05

COMPONENTS = ("delta", "ngram", "rhythm", "vocab", "punct", "shape")

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


def load_corpus(root: Path) -> list[Doc]:
    """Load voice-pack-shaped directories: <root>/<author>/training-data/*.

    Deliberately the same layout as a voice pack, so `examples/voices` benches as-is
    and a purpose-built evaluation corpus (see docs/metrics.md §4.1) drops in beside it.
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
            text = extract_text(f)
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


def default_scorers() -> dict[str, dict[str, float]]:
    """The shipped composite, every component alone, and the ablations worth arguing about."""
    scorers = {"composite": dict(WEIGHTS)}
    for c in COMPONENTS:
        scorers[c] = _only(c)
    scorers["no-vocab"] = _renormalized(("vocab",))
    scorers["no-vocab-rhythm-shape"] = _renormalized(("vocab", "rhythm", "shape"))
    scorers["delta+ngram"] = {"delta": 0.5, "ngram": 0.5, "rhythm": 0.0,
                              "vocab": 0.0, "punct": 0.0, "shape": 0.0}
    scorers["delta+ngram+punct"] = {"delta": 0.4, "ngram": 0.4, "rhythm": 0.0,
                                    "vocab": 0.0, "punct": 0.2, "shape": 0.0}
    return scorers


def combine(components: dict[str, float], weights: dict[str, float]) -> float:
    """Recombine the six components into one 0-100 score under a given weighting."""
    return 100.0 * sum(weights.get(c, 0.0) * components.get(c, 0.0) for c in COMPONENTS)


# ---------- trials ----------


@dataclass
class Trial:
    ref_author: str
    ref_exclude: str      # the work (or doc path) held out of the reference
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
) -> list[Trial]:
    """Build and score every trial. `level` is 'work' (topic-controlled) or 'doc' (leaky)."""
    rng = random.Random(seed)
    authors = sorted({d.author for d in docs})
    if len(authors) < 2:
        raise RuntimeError(
            f"bench needs at least 2 authors to form different-author trials (found: {authors})"
        )

    key = (lambda d: d.work) if level == "work" else (lambda d: d.path)
    trials: list[Trial] = []

    for author in authors:
        own = [d for d in docs if d.author == author]
        others = [d for d in docs if d.author != author]
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
    return out


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
          skip_content_control: bool = False, progress=None) -> dict:
    """Full bench run. Returns a JSON-serializable report."""
    docs = load_corpus(root)
    if not docs:
        raise RuntimeError(f"no documents found under {root} (expected <author>/training-data/*)")

    trials = run_trials(docs, lengths, queries_per_cell, seed, "work", progress)
    result = evaluate(trials, None, lengths, max_fpr)
    result["corpus"] = corpus_summary(docs)
    result["protocol"] = {
        "leave_one_out": "work",
        "lengths": list(lengths),
        "queries_per_cell": queries_per_cell,
        "seed": seed,
        "max_fpr": max_fpr,
    }

    if not skip_content_control:
        leaky_trials = run_trials(docs, lengths, queries_per_cell, seed, "doc", progress)
        result["content_control"] = content_control(
            result, evaluate(leaky_trials, None, lengths, max_fpr)
        )

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
