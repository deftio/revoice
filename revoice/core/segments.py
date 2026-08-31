"""Content-blend analysis: what KINDS of text a document contains, segment by segment.

Handles the "someone concatenated a bunch of unrelated stuff" case: the document is
split into paragraph segments, each is typed deterministically, adjacent same-type
segments merge, and a heterogeneity index says how mixed the whole thing is.

Content types (deterministic, no LLM):
  narrative     dialogue, first/third-person storytelling, past-tense flow
  expository    argument/explanation prose (essays, technical writing, docs)
  numeric       tables, data dumps, digit-dense text
  code          code blocks / markup / log-ish lines
  list          bullet/enumeration runs
  fragment      headers, stubs, too short to type
"""

from __future__ import annotations

import re
import statistics

from revoice.core.stylometry import fingerprint, tokenize

DIALOG_RX = re.compile(r'["“”]')
PRONOUN_RX = re.compile(r"\b(I|he|she|we|they|him|her|me|us|my|his|their)\b", re.IGNORECASE)
PAST_RX = re.compile(r"\b\w+ed\b|\b(said|was|were|had|went|came|saw|took|thought)\b", re.IGNORECASE)
CODE_RX = re.compile(
    r"[{}]|::|->|==|\bdef\b|\breturn\b|\bvoid\b|\bimport\b|</?\w+>|^\s{4,}\S|^\s*(?:\$|#include|//)",
    re.MULTILINE,
)
LIST_RX = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s", re.MULTILINE)
NOMINAL_RX = re.compile(r"\w+(?:tion|ment|ness|ity|ance|ence)s?\b", re.IGNORECASE)


def _digit_density(text: str) -> float:
    alnum = [c for c in text if c.isalnum()]
    return sum(c.isdigit() for c in alnum) / max(len(alnum), 1)


def classify_segment(text: str) -> str:
    if _digit_density(text) > 0.15 and len(text) > 40:
        return "numeric"
    words, sentences = tokenize(text)
    if len(words) < 12:
        return "fragment"
    if len(CODE_RX.findall(text)) >= max(3, len(text) // 200):
        return "code"
    list_lines = len(LIST_RX.findall(text))
    total_lines = max(text.count("\n") + 1, 1)
    if list_lines / total_lines > 0.5 and total_lines >= 3:
        return "list"
    n = max(len(words), 1)
    dialog = len(DIALOG_RX.findall(text)) / n
    pronouns = len(PRONOUN_RX.findall(text)) / n
    past = len(PAST_RX.findall(text)) / n
    nominal = len(NOMINAL_RX.findall(text)) / n
    narrative_score = 3.0 * dialog + 1.5 * pronouns + past
    expository_score = 4.0 * nominal + 0.05
    return "narrative" if narrative_score > expository_score else "expository"


def analyze_blend(text: str, min_segment_chars: int = 200) -> dict:
    """Split into paragraph segments, type each, merge runs, compute blend + heterogeneity."""
    # protect fenced code blocks as single paragraphs, then split on blank lines
    fenced = re.split(r"(```.*?```|~~~.*?~~~)", text, flags=re.DOTALL)
    paras: list[str] = []
    for part in fenced:
        if part.startswith(("```", "~~~")):
            paras.append(part)
        else:
            paras.extend(p for p in re.split(r"\n\s*\n", part) if p.strip())

    # classify each paragraph FIRST (so type boundaries are never averaged away),
    # then merge adjacent same-type runs; fragments attach to the following run
    typed = []
    for p in paras:
        t = "code" if p.startswith(("```", "~~~")) else classify_segment(p)
        typed.append((t, p))

    merged: list[dict] = []
    for t, s in typed:
        if t == "fragment" and merged:
            merged[-1]["chars"] += len(s)  # fold tiny fragments into the previous run
            merged[-1]["text"] += "\n\n" + s
        elif merged and merged[-1]["type"] == t:
            merged[-1]["chars"] += len(s)
            merged[-1]["text"] = merged[-1]["text"] + "\n\n" + s
        else:
            merged.append({"type": t if t != "fragment" else "expository", "chars": len(s), "text": s})

    total = max(sum(m["chars"] for m in merged), 1)
    blend: dict[str, float] = {}
    for m in merged:
        blend[m["type"]] = blend.get(m["type"], 0.0) + m["chars"] / total
    blend = {k: round(v, 3) for k, v in sorted(blend.items(), key=lambda kv: -kv[1])}

    # stylometric heterogeneity: variability across ~800-char prose windows
    # (windows, not merged runs, so one giant merged run can't hide internal shifts)
    windows: list[str] = []
    for m in merged:
        if m["type"] in ("narrative", "expository"):
            t = m["text"]
            windows.extend(t[i : i + 800] for i in range(0, max(len(t) - 400, 1), 800))
    prose = [w for w in windows if len(w) > 300]
    hetero = 0.0
    if len(prose) >= 2:
        feats = []
        for w in prose:
            fp = fingerprint(w)
            feats.append((fp["mean_sentence_len"], fp["mean_word_len"] * 10, fp["type_token_ratio"] * 50))
        dims = list(zip(*feats, strict=False))
        cvs = []
        for d in dims:
            mu = statistics.mean(d)
            if mu:
                cvs.append(statistics.pstdev(d) / mu)
        hetero = round(min(statistics.mean(cvs) * 2.5, 1.0), 3) if cvs else 0.0

    n_switches = sum(1 for i in range(1, len(merged)) if merged[i]["type"] != merged[i - 1]["type"])
    top = max(blend.values(), default=0.0)
    if hetero > 0.5 or (n_switches >= 3 and hetero > 0.25) or (len(blend) >= 3 and top < 0.7):
        verdict = "concatenation-of-unrelated-content"
    elif (len(blend) >= 2 and top < 0.8) or n_switches >= 2:
        verdict = "blended"
    elif len(blend) == 1 and hetero < 0.25 and n_switches == 0:
        verdict = "homogeneous"
    else:
        verdict = "mostly-uniform"

    return {
        "segments": [{"type": m["type"], "chars": m["chars"]} for m in merged],
        "blend": blend,
        "type_switches": n_switches,
        "style_heterogeneity": hetero,   # 0 = one consistent voice, 1 = wildly mixed
        "verdict": verdict,
    }
