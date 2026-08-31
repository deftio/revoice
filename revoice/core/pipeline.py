"""The revoice pipeline: spans → attribution → rewrite → validate → lint → reassemble.

Minimal-touch principle enforced here: a span is only rewritten when we have positive
reason to (off-target attribution, lint hits, or explicit full-strength). Validation
failure → the original text is kept (safe default) and flagged in the diff.
"""

from __future__ import annotations

import json
import re

from revoice.core import lint as lintmod
from revoice.core.metrics import load_baselines, load_calibration, score_text
from revoice.core.spans import parse, reassemble, rewritable
from revoice.core.voicepack import VoicePack
from revoice.providers.base import Provider

REWRITE_SYSTEM = """REWRITE_SPAN
You rewrite one span of text in the voice of the author "{voice}" ({register} register).
This is register transfer within one author — not improvement, not expansion.

The author's voice profile:
{profile}

{style_section}
Samples of the author's real writing in this register:
{exemplars}

Rules — all mandatory:
- Preserve meaning exactly. Every number, name, unit, and claim stays.
- Preserve inline markdown exactly: links [x](y), `code`, *emphasis*, bold.
- Similar length (within ~30% of the original).
- Strength {strength}: 0 = only fix typos/punctuation; 1 = fully recast into the voice.
- Never use these AI-tell phrases or patterns: {tells}
- The user message may include read-only CONTEXT (surrounding text). Use it for
  pronouns, references, and flow — but rewrite ONLY the span after "SPAN TO REWRITE:".
- Output ONLY the rewritten span text. No preamble, no quotes, no commentary."""

COHESION_SYSTEM = """COHESION_EDIT
You are the final editing pass over a rewritten document in the voice of "{voice}".
The user gives you the passage PRECEDING a span (read-only context) and the span itself.
Fix ONLY cohesion problems in the span: broken pronoun references, jarring transitions
from the preceding passage, or an abrupt register shift. If the span reads fine in
context — and it usually will — return it EXACTLY unchanged.
Never change meaning, numbers, names, or markdown. Output only the span text.

PRECEDING PASSAGE (read-only):
{prev}"""

MIN_WORDS_ATTRIB = 25  # spans shorter than this skip stylometric attribution (too noisy)


def _load_profile(pack: VoicePack, register: str) -> str:
    f = pack.profiles_dir / f"{register}.json"
    if not f.is_file():
        return "(no profile — write naturally, plainly, without AI mannerisms)"
    p = json.loads(f.read_text())
    return "\n".join(f"- {k}: {v}" for k, v in p.items() if v and k in
                     ("voice_summary", "sentence_rhythm", "vocabulary", "habits", "never_does"))


def _load_exemplars(pack: VoicePack, register: str, k: int = 3, chars: int = 700) -> str:
    f = pack.exemplars_dir / f"{register}.json"
    if not f.is_file():
        return "(none available)"
    ex = json.loads(f.read_text())[:k]
    return "\n\n".join(f"<sample>\n{x['excerpt'][:chars]}\n</sample>" for x in ex)


def _numbers(text: str) -> list[str]:
    return sorted(re.findall(r"\d+(?:[.,]\d+)*", text))


def _validate(orig: str, new: str) -> str | None:
    """Return failure reason or None."""
    if not new.strip():
        return "empty"
    if _numbers(orig) != _numbers(new):
        return "numbers-changed"
    ow, nw = len(orig.split()), len(new.split())
    if ow >= 8 and not (0.55 <= nw / max(ow, 1) <= 1.9):
        return f"length-ratio ({ow}->{nw})"
    # proper nouns (crude): capitalized words not at sentence start must survive
    orig_proper = set(re.findall(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,})", orig))
    lost = [p for p in orig_proper if p not in new]
    if lost:
        return f"entities-lost ({', '.join(lost[:3])})"
    return None


def revoice_document(
    text: str,
    pack: VoicePack,
    provider: Provider,
    register: str | None = None,
    strength: float = 0.7,
    progress=None,
    critic: Provider | None = None,
    judge_votes: int = 1,
    cohesion: bool = False,
) -> tuple[str, dict]:
    """Returns (output_text, diff_report)."""
    baselines = load_baselines(pack)
    calib = load_calibration(pack)
    if not baselines:
        raise RuntimeError(f"voice '{pack.name}' has no baselines — run: revoice learn {pack.name}")

    # infer register from whole document if not given
    if register is None:
        scored = {r: score_text(text, b)["composite"] for r, b in baselines.items()}
        register = max(scored, key=scored.get)
    elif register not in baselines:
        raise RuntimeError(f"register '{register}' not in voice '{pack.name}' (have: {sorted(baselines)})")

    baseline = baselines[register]
    band = calib.get(register, {})
    on_target_floor = band.get("self_mean", 70) - band.get("self_std", 10)

    from revoice.core.style import apply_hard_swaps, load_style, render_prompt_section

    style = load_style(pack.params_dir)
    style_section = render_prompt_section(style)
    patterns = lintmod.load_patterns(pack.params_dir)
    tell_names = ", ".join(sorted({n for _, n in patterns})[:18])
    system = REWRITE_SYSTEM.format(
        voice=pack.name,
        register=register,
        profile=_load_profile(pack, register),
        style_section=(style_section + "\n") if style_section else "",
        exemplars=_load_exemplars(pack, register),
        strength=strength,
        tells=tell_names,
    )

    from revoice.core.preflight import CITE_RX, DIALOG_RX, MATH_RX, URL_RX
    from revoice.core.segments import analyze_blend

    het_before = analyze_blend(text)["style_heterogeneity"]
    spans = parse(text)
    report = {"voice": pack.name, "register": register, "strength": strength, "spans": []}
    prev_text = ""  # rolling read-only context (final text of the previous rewritable span)

    def _span_cautions(t: str) -> list[str]:
        c = []
        if len(MATH_RX.findall(t)) >= 2:
            c.append("math/units present: preserve all notation, values, and units verbatim")
        if URL_RX.search(t):
            c.append("URLs present: preserve exactly")
        if CITE_RX.search(t):
            c.append("citations present: preserve exactly")
        if len(DIALOG_RX.findall(t)) >= 1:
            c.append("quoted speech present: preserve quoted content")
        return c

    def _user_msg(t: str) -> str:
        parts = []
        cautions = _span_cautions(t)
        if cautions:
            parts.append("CAUTIONS:\n" + "\n".join(f"- {c}" for c in cautions))
        if prev_text:
            parts.append(f"CONTEXT (read-only, do not rewrite):\n{prev_text[-600:]}")
        parts.append(f"SPAN TO REWRITE:\n{t}")
        return "\n\n".join(parts)

    for s in rewritable(spans):
        entry = {"id": s.id, "kind": s.kind, "original": s.text}
        words = len(s.text.split())

        # --- attribution ---
        tells = lintmod.scan(s.text, patterns)
        if strength >= 0.95:
            verdict = "rewrite"
        elif tells:
            verdict = "rewrite"  # AI tells present → definitely not the author's voice
        elif words < MIN_WORDS_ATTRIB:
            verdict = "rewrite" if strength > 0 else "pass"  # too short to attribute; err per strength
        else:
            comp = score_text(s.text, baseline)["composite"]
            entry["attribution_score"] = comp
            verdict = "pass" if comp >= on_target_floor else "rewrite"
        entry["input_tells"] = tells

        if verdict == "pass" or strength == 0 and not tells:
            entry["status"] = "unchanged"
            report["spans"].append(entry)
            prev_text = s.text
            if progress:
                progress(s.id, "on-target, untouched")
            continue

        # --- rewrite (with one lint-retry); rolling context + cautions in user msg ---
        try:
            new = provider.complete(system, _user_msg(s.text)).strip()
            out_tells = lintmod.scan(new, patterns)
            if out_tells:
                new2 = provider.complete(
                    system + f"\nYour previous attempt used banned patterns: {', '.join(out_tells)}. Do not.",
                    _user_msg(s.text),
                ).strip()
                if not lintmod.scan(new2, patterns):
                    new = new2
                    out_tells = []
        except Exception as e:  # noqa: BLE001
            entry["status"] = "error"
            entry["error"] = str(e)
            report["spans"].append(entry)
            prev_text = s.text
            if progress:
                progress(s.id, f"ERROR {e}")
            continue

        # --- deterministic hard swaps (style.yaml `swaps`) ---
        new, swapped = apply_hard_swaps(new, style)
        if swapped:
            entry["hard_swaps"] = swapped

        # --- validate ---
        fail = _validate(s.text, new)
        if fail:
            entry["status"] = "validation-failed-kept-original"
            entry["failure"] = fail
            entry["rejected"] = new
        else:
            # --- rubric critique (one dimension per call; scores mapped in code) ---
            if critic is not None:
                from revoice.core.rubrics import judge_all, load_rubrics

                verdicts = judge_all(critic, load_rubrics(pack.params_dir), s.text, new, judge_votes)
                entry["rubric"] = verdicts
                if verdicts["rejected_by"]:
                    entry["status"] = f"rubric-rejected-kept-original ({','.join(verdicts['rejected_by'])})"
                    entry["rejected"] = new
                    report["spans"].append(entry)
                    prev_text = s.text
                    if progress:
                        progress(s.id, entry["status"])
                    continue
            entry["status"] = "rewritten"
            entry["new"] = new
            entry["output_tells"] = out_tells
            s.text = new
        report["spans"].append(entry)
        prev_text = s.text
        if progress:
            progress(s.id, entry["status"])

    # --- pass 2: cohesion edit over seams (rewritten spans with a preceding span) ---
    if cohesion:
        entries = {e["id"]: e for e in report["spans"]}
        rw_spans = rewritable(spans)
        for i, s in enumerate(rw_spans):
            e = entries.get(s.id, {})
            if i == 0 or e.get("status") != "rewritten":
                continue
            prev_final = rw_spans[i - 1].text
            try:
                fixed = provider.complete(
                    COHESION_SYSTEM.format(voice=pack.name, prev=prev_final[-800:]), s.text
                ).strip()
            except Exception:  # noqa: BLE001 — cohesion is best-effort
                continue
            if fixed and fixed != s.text and _validate(s.text, fixed) is None \
                    and not lintmod.scan(fixed, patterns):
                e["cohesion_edited"] = True
                e["pre_cohesion"] = s.text
                e["new"] = fixed
                s.text = fixed
                if progress:
                    progress(s.id, "cohesion-edited")

    n = {"unchanged": 0, "rewritten": 0, "validation-failed-kept-original": 0, "error": 0}
    for e in report["spans"]:
        n[e["status"]] = n.get(e["status"], 0) + 1
    n["cohesion-edited"] = sum(1 for e in report["spans"] if e.get("cohesion_edited"))
    report["summary"] = n
    out_text = reassemble(spans)
    report["heterogeneity"] = {"before": het_before,
                               "after": analyze_blend(out_text)["style_heterogeneity"]}
    return out_text, report
