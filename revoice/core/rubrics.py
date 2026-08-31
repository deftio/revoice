"""revoice's pack-aware wrapper around the generic `revoice.rubric` module.

The generic engine (anchored categories, code-side scoring, voting) lives in
revoice/rubric/ and knows nothing about voice packs or providers. This file owns
what's revoice-specific: the default rewrite-judging rubric template, the pack
file location, and the Provider -> callable adaptation.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from revoice.providers.base import Provider
from revoice.rubric import judge_all as _judge_all

TEMPLATE = """\
# revoice judging rubrics — anchored categorical scales. Edit freely; `learn`
# never overwrites this file once it exists.
#
# Schema and usage: see revoice/rubric/README.md (the engine is generic — the
# model answers with a choice NAME; scores/weights/composite are computed in code).

dimensions:

  voice_fidelity:
    description: >
      How much the rewritten text reads as this author's own hand, in the target
      register — judged against the writing samples provided.
    weight: 0.4
    choices:
      unmistakable: "characteristically the author; rhythm, word choice, and habits all present"
      plausible: "consistent with the author; nothing rings false"
      generic: "competent prose, but anyone could have written it"
      foreign: "another voice is audible, including AI register"
    scores: {unmistakable: 1.0, plausible: 0.75, generic: 0.35, foreign: 0.0}
    reject_below: 0.1

  integrity:
    description: >
      Whether every claim, fact, number, and implication in the rewritten text is
      supported by the original text. The rewrite may not add, drop, or bend claims.
    weight: 0.35
    choices:
      faithful: "every claim in the rewrite is supported by the original; none lost"
      shaded: "no new claims, but emphasis or hedging has shifted meaningfully"
      unsupported: "the rewrite contains at least one claim the original does not support"
      contradicts: "the rewrite states something the original contradicts"
    scores: {faithful: 1.0, shaded: 0.6, unsupported: 0.0, contradicts: 0.0}
    reject_below: 0.3

  verbosity:
    description: >
      Length and density of the rewrite relative to the original: does it say the
      same things in a similar amount of space?
    weight: 0.15
    choices:
      matched: "similar length and density; nothing padded or squeezed"
      compact: "noticeably tighter, but nothing substantive lost"
      padded: "longer with filler, restatement, or scaffolding"
      bloated: "substantially longer without added substance"
    scores: {matched: 1.0, compact: 0.85, padded: 0.35, bloated: 0.0}

  ai_register:
    description: >
      Presence of machine-writing mannerisms: stock transitions, hedge-then-assert,
      rule-of-three parallelism, tidy summarizing closers, promotional adjectives.
    weight: 0.1
    choices:
      clean: "no AI mannerisms detectable"
      trace: "one or two mild tells"
      flavored: "several tells; a reader might suspect assistance"
      obvious: "unmistakably machine-flavored"
    scores: {clean: 1.0, trace: 0.7, flavored: 0.25, obvious: 0.0}
"""


def load_rubrics(params_dir: Path) -> dict:
    f = params_dir / "rubrics.yaml"
    if not f.is_file():
        return yaml.safe_load(TEMPLATE)["dimensions"]
    return (yaml.safe_load(f.read_text()) or {}).get("dimensions", {})


def write_template(params_dir: Path) -> bool:
    f = params_dir / "rubrics.yaml"
    if f.is_file():
        return False
    params_dir.mkdir(parents=True, exist_ok=True)
    f.write_text(TEMPLATE)
    return True


def judge_all(provider: Provider, rubrics: dict, original: str, rewrite: str,
              k: int = 1, progress=None) -> dict:
    """Pair-judge a rewrite against its original using the generic engine."""
    return _judge_all(provider.complete, rubrics, candidate=rewrite,
                      original=original, k=k, progress=progress)
