"""rubric — anchored categorical judging for LLM (or human) output.

Standalone module: no imports from the rest of revoice. Sole dependency surface:
a callable `llm(system: str, user: str) -> str` and pyyaml.

Core idea: the model CLASSIFIES (picks one named, behaviorally-anchored choice
per dimension); the code COMPUTES (choice -> score mapping, weights, composite,
vote tallies). No LLM-generated numbers, ever.

    from revoice.rubric import judge_all, load_rubrics_file

    rubrics = load_rubrics_file("my-rubrics.yaml")
    result = judge_all(my_llm, rubrics, original=None, candidate=text, k=3)
    # result["composite"], result["dimensions"][...]["choice" / "agreement"]

See README.md in this directory.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import yaml

Llm = Callable[[str, str], str]

# The scoring CONTRACT this module implements — the model picks a named choice, the code
# maps choices to numbers — has not changed and is not expected to, hence 1.x. A MAJOR
# bump would mean results recorded earlier are no longer comparable to new ones.
__version__ = "1.0.0"

__all__ = [
    "judge_all", "judge_dimension", "load_rubrics_file", "vote_metrics", "Llm",
    "version", "describe", "rubric_signature",
    "version_info",
]


# --- runtime version support ---------------------------------------------------
# Every package in this family reports its own version at runtime, in a form you can
# print and a form you can compare: bitwrench has `bw.version` / `bw.versionInfo` /
# `bw.getVersion()`, fr_math has FR_MATH_VERSION alongside a packed FR_MATH_VERSION_HEX.
# A string is for humans and logs; a tuple is for `if version_info() >= (0, 2)`, which
# string comparison gets wrong the moment a component reaches double digits ("0.1.10"
# sorts before "0.1.9").

__version_info__ = tuple(int(p) for p in __version__.split("."))


def version_info() -> tuple[int, ...]:
    """The version as integers, for comparison. `version()` is the one to print."""
    return __version_info__


def version() -> str:
    """The engine version, for recording alongside any result it produced."""
    return __version__


def rubric_signature(rubrics: dict) -> str:
    """Short stable hash of the rubric spec that produced a judgment.

    The version alone is not enough for reproducibility: the numbers come from the
    caller's YAML — its dimensions, choices, score mappings and weights — so two runs of
    the same engine version are comparable only if they used the same spec. Recording
    this beside the version is what makes "why did last month's composite differ?"
    answerable instead of archaeological.
    """
    payload = json.dumps(
        {name: {"choices": sorted(dim.get("choices") or {}),
                "scores": dict(sorted((dim.get("scores") or {}).items())),
                "weight": dim.get("weight"),
                "reject_below": dim.get("reject_below")}
         for name, dim in sorted(rubrics.items())},
        sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def describe(rubrics: dict | None = None) -> dict:
    """Everything a caller should record to make a judgment reproducible."""
    out = {"name": "rubric", "version": __version__,
           "scoring": "model classifies, code computes", "llm_numbers": False}
    if rubrics is not None:
        out["rubric_signature"] = rubric_signature(rubrics)
        out["dimensions"] = sorted(rubrics)
    return out

_SYSTEM = """RUBRIC_JUDGE
You judge ONE dimension of a piece of text. Answer with exactly one word:
one of the choice names given. No other text, no punctuation, no explanation.

Dimension: {name}
{description}

Choices:
{choices}
{examples}"""

_USER_PAIR = """ORIGINAL:
{original}

CANDIDATE:
{candidate}

Answer with one choice name for the dimension "{name}":"""

_USER_SINGLE = """TEXT:
{candidate}

Answer with one choice name for the dimension "{name}":"""


def load_rubrics_file(path: str | Path) -> dict:
    """Load a rubrics YAML file; returns the `dimensions` mapping."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    return data.get("dimensions", data)


def _parse_choice(raw: str, names: list[str]) -> str | None:
    for w in re.findall(r"[a-z_]+", raw.lower()):
        if w in names:
            return w
    return None


def vote_metrics(votes: list[str], k_choices: int) -> dict:
    """Distribution-aware agreement descriptors for a set of votes over k choices.

    Agreement is a property of the vote DISTRIBUTION, not a single scalar
    (winner selection is a decision mechanism, not an agreement measure).
    Reported together:

      winner        modal choice (identification only — no agreement semantics)
      winner_share  p of the modal choice
      winner_gap    p(1st) - p(2nd): local surety of the winner
      n_eff         effective number of answers, 1/Σp² (1 = unanimous,
                    k = uniform); scale-free, comparable across rubrics
      a_k           k-normalized decisiveness, (Σp² - 1/k)/(1 - 1/k):
                    1 = unanimous, 0 = uniform over the offered choice space

    n_eff and a_k answer different questions: a 50/50 split has n_eff = 2
    regardless of k, but a_k = 0 when k = 2 and a_k > 0 when k = 7.
    """
    if not votes:
        return {"winner": None, "winner_share": 0.0, "winner_gap": 0.0,
                "n_eff": 0.0, "a_k": 0.0, "counts": {}}
    tally = Counter(votes)
    n = len(votes)
    ps = sorted((c / n for c in tally.values()), reverse=True)
    c_raw = sum(p * p for p in ps)
    winner, top = tally.most_common(1)[0]
    return {
        "winner": winner,
        "winner_share": round(top / n, 3),
        "winner_gap": round(ps[0] - (ps[1] if len(ps) > 1 else 0.0), 3),
        "n_eff": round(1.0 / c_raw, 3),
        "a_k": round((c_raw - 1.0 / k_choices) / (1.0 - 1.0 / k_choices), 3)
        if k_choices > 1 else 1.0,
        "counts": dict(tally),
    }


def judge_dimension(llm: Llm, name: str, dim: dict, candidate: str,
                    original: str | None = None, k: int = 1) -> dict:
    """Judge one dimension. k>1 -> majority vote; agreement rate recorded.

    Returns {choice, votes, agreement, score}. score is None if the rubric
    defines no `scores` mapping (labels-only mode is valid).
    """
    names = list(dim["choices"])
    choices = "\n".join(f"- {n}: {d}" for n, d in dim["choices"].items())
    ex = ""
    if dim.get("examples"):
        ex += "\nExamples:\n" + "\n".join(f"- {e}" for e in dim["examples"])
    if dim.get("counter_examples"):
        ex += "\nCounter-examples:\n" + "\n".join(f"- {e}" for e in dim["counter_examples"])
    system = _SYSTEM.format(name=name, description=dim.get("description", ""),
                            choices=choices, examples=ex)
    user = (_USER_PAIR.format(original=original, candidate=candidate, name=name)
            if original is not None else _USER_SINGLE.format(candidate=candidate, name=name))

    votes = []
    for _ in range(max(k, 1)):
        c = _parse_choice(llm(system, user), names)
        if c:
            votes.append(c)
    if not votes:
        return {"choice": None, "votes": [], "agreement": vote_metrics([], len(names)), "score": None}
    m = vote_metrics(votes, len(names))
    return {"choice": m["winner"], "votes": votes, "agreement": m,
            "score": dim.get("scores", {}).get(m["winner"])}


def judge_all(llm: Llm, rubrics: dict, candidate: str, original: str | None = None,
              k: int = 1, progress=None) -> dict:
    """Judge every dimension, one LLM call each (times k). Composite computed here.

    original=None -> single-text mode (judge the candidate on its own).
    Returns {dimensions: {...}, composite, rejected_by: [dims whose score fell
    below their `reject_below` threshold]}.
    """
    dims, total_w, acc, rejected = {}, 0.0, 0.0, []
    for name, dim in rubrics.items():
        r = judge_dimension(llm, name, dim, candidate, original, k)
        dims[name] = r
        if progress:
            a = r["agreement"]
            progress(name, f"{r['choice']} (share {a['winner_share']}, gap {a['winner_gap']}, n_eff {a['n_eff']})")
        if r["score"] is not None:
            w = float(dim.get("weight", 1.0))
            acc += w * r["score"]
            total_w += w
            if "reject_below" in dim and r["score"] < float(dim["reject_below"]):
                rejected.append(name)
    return {"dimensions": dims,
            "composite": round(acc / total_w, 3) if total_w else None,
            "rejected_by": rejected,
            "engine": describe(rubrics)}
