"""Stats report: one dict, four renderings (text handled by the CLI, plus json/md/html).

The dict is the canonical shape — the API returns it verbatim; md/html are renderings.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from revoice.core.segments import analyze_blend
from revoice.core.stylometry import SENT_HIST_BINS, fingerprint
from revoice.core.voicepack import VoicePack

BAR_W = 24


def build_report(text: str, source: str = "", pack: VoicePack | None = None,
                 register: str | None = None) -> dict:
    rep: dict = {
        "source": source,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fingerprint": fingerprint(text),
        "content": analyze_blend(text),
    }
    if pack is not None:
        from revoice.core.metrics import score_against_pack

        m = score_against_pack(text, pack, register)
        # trim fingerprints out of per-register results (already at top level)
        for r in m["results"].values():
            r.pop("fingerprint", None)
        rep["voice"] = pack.name
        rep["match"] = m
    return rep


# ---------- markdown ----------

def _mdbar(v: float) -> str:
    n = int(round(v * BAR_W))
    return "█" * n + "░" * (BAR_W - n)


def _hist_labels() -> list[str]:
    return [f"{SENT_HIST_BINS[i]}–{SENT_HIST_BINS[i+1]-1}" if SENT_HIST_BINS[i + 1] < 10_000
            else f"{SENT_HIST_BINS[i]}+" for i in range(len(SENT_HIST_BINS) - 1)]


def render_md(rep: dict) -> str:
    fp = rep["fingerprint"]
    c = rep["content"]
    L = [f"# revoice stats — {rep['source'] or 'document'}", "",
         f"*generated {rep['generated']}*", "",
         "## Overview", "",
         "| words | sentences | flesch | type/token | mean sent len | burstiness |",
         "|---|---|---|---|---|---|",
         f"| {fp['words']} | {fp['sentences']} | {fp['flesch']} | {fp['type_token_ratio']} "
         f"| {fp['mean_sentence_len']} ± {fp['sentence_len_std']} | {fp['burstiness']} |", "",
         "## Sentence-length distribution", "", "```"]
    for lab, v in zip(_hist_labels(), fp["sent_len_hist"], strict=False):
        L.append(f"{lab:>6s} {_mdbar(v)} {v:.0%}")
    L += ["```", "", "## Content blend", "", "```"]
    for t, frac in c["blend"].items():
        L.append(f"{t:<11s} {_mdbar(frac)} {frac:.0%}")
    L += ["```", "",
          f"{len(c['segments'])} segments · {c['type_switches']} type switches · "
          f"style heterogeneity {c['style_heterogeneity']:.2f} — **{c['verdict']}**", ""]
    punct = sorted(fp["punct_per_sentence"].items(), key=lambda kv: -kv[1])[:6]
    L += ["## Style markers", "",
          "punctuation/sentence: " + " · ".join(f"`{p}` {v}" for p, v in punct),
          f"-ly adverbs {fp['adverb_ly_rate']:.2%} · nominalizations {fp['nominalization_rate']:.2%} · "
          f"passive-ish {fp['passive_rate']:.2f}/sentence", ""]
    if "match" in rep:
        m = rep["match"]
        L += [f"## Voice match — `{rep['voice']}`", "",
              "| register | composite | corpus self-score | delta (raw) | ngram | rhythm | vocab | punct | shape |",
              "|---|---|---|---|---|---|---|---|---|"]
        for reg, r in sorted(m["results"].items(), key=lambda kv: -kv[1]["composite"]):
            cal = r.get("calibration", {})
            cal_s = f"{cal.get('self_mean', '—')} ± {cal.get('self_std', '—')}" if cal else "—"
            co = r["components"]
            mark = "**→** " if reg == m["best_register"] else ""
            L.append(f"| {mark}{reg} | {r['composite']} | {cal_s} | {co['delta']} ({r['burrows_delta']}) "
                     f"| {co['ngram']} | {co['rhythm']} | {co['vocab']} | {co['punct']} | {co['shape']} |")
        L.append("")
        if not m["results"][m["best_register"]].get("reliable", True):
            L.append("> note: <150 words — scores are noisy at this length")
            L.append("")
    return "\n".join(L)


# ---------- html (bitwrench) ----------

def _hbar(v: float, color: str = "#4a90d9") -> str:
    return (f'<div style="background:#e8e8e8;border-radius:3px;height:14px;width:240px;display:inline-block;'
            f'vertical-align:middle"><div style="background:{color};height:14px;border-radius:3px;'
            f'width:{max(int(v * 100), 1)}%"></div></div> <span style="font-size:0.9em">{v:.0%}</span>')


def _verdict_color(verdict: str) -> str:
    if verdict in ("homogeneous", "mostly-uniform"):
        return "#5cb85c"
    return "#f0ad4e" if verdict == "blended" else "#d9534f"


def render_html(rep: dict) -> str:
    fp = rep["fingerprint"]
    c = rep["content"]
    rows_hist = "".join(f"<tr><td>{lab}</td><td>{_hbar(v)}</td></tr>"
                        for lab, v in zip(_hist_labels(), fp["sent_len_hist"], strict=False))
    rows_blend = "".join(f"<tr><td>{t}</td><td>{_hbar(frac, '#5cb85c')}</td></tr>"
                         for t, frac in c["blend"].items())
    punct = sorted(fp["punct_per_sentence"].items(), key=lambda kv: -kv[1])[:6]
    match_html = ""
    if "match" in rep:
        m = rep["match"]
        body = ""
        for reg, r in sorted(m["results"].items(), key=lambda kv: -kv[1]["composite"]):
            cal = r.get("calibration", {})
            cal_s = f"{cal.get('self_mean', '—')} ± {cal.get('self_std', '—')}" if cal else "—"
            co = r["components"]
            star = "→ " if reg == m["best_register"] else ""
            body += (f"<tr><td>{star}{reg}</td><td><b>{r['composite']}</b></td><td>{cal_s}</td>"
                     f"<td>{co['delta']} ({r['burrows_delta']})</td><td>{co['ngram']}</td>"
                     f"<td>{co['rhythm']}</td><td>{co['vocab']}</td><td>{co['punct']}</td><td>{co['shape']}</td></tr>")
        match_html = f"""
  <h2>Voice match — {rep['voice']}</h2>
  <table class="bw-table"><thead><tr><th>register</th><th>composite</th><th>self-score</th>
  <th>delta</th><th>ngram</th><th>rhythm</th><th>vocab</th><th>punct</th><th>shape</th></tr></thead>
  <tbody>{body}</tbody></table>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>revoice stats — {rep['source']}</title>
<script src="https://cdn.jsdelivr.net/gh/deftio/bitwrench/bitwrench.min.js"></script>
<style>
body{{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:860px;margin:2em auto;
padding:0 1em;color:#222;line-height:1.5}}
h1{{border-bottom:2px solid #4a90d9;padding-bottom:.3em}}
table{{border-collapse:collapse;width:100%;margin:.5em 0}}
td,th{{padding:4px 10px;text-align:left;border-bottom:1px solid #eee;font-size:.95em}}
.verdict{{display:inline-block;padding:.2em .7em;border-radius:1em;color:#fff;font-weight:600}}
.meta{{color:#888;font-size:.85em}}
@media(max-width:600px){{td,th{{padding:3px 5px;font-size:.85em}}}}
</style></head><body>
<script>if(window.bw){{bw.DOM("body").length}}</script>
<h1>revoice stats <span class="meta">— {rep['source']}</span></h1>
<p class="meta">generated {rep['generated']}</p>
<h2>Overview</h2>
<table><tr><th>words</th><th>sentences</th><th>flesch</th><th>type/token</th><th>sent len</th><th>burstiness</th></tr>
<tr><td>{fp['words']}</td><td>{fp['sentences']}</td><td>{fp['flesch']}</td><td>{fp['type_token_ratio']}</td>
<td>{fp['mean_sentence_len']} ± {fp['sentence_len_std']}</td><td>{fp['burstiness']}</td></tr></table>
<h2>Sentence-length distribution</h2>
<table>{rows_hist}</table>
<h2>Content blend</h2>
<table>{rows_blend}</table>
<p>{len(c['segments'])} segments · {c['type_switches']} type switches ·
style heterogeneity {c['style_heterogeneity']:.2f} &nbsp;
<span class="verdict" style="background:{_verdict_color(c['verdict'])}">{c['verdict']}</span></p>
<h2>Style markers</h2>
<p>punctuation/sentence: {' · '.join(f"<code>{p}</code> {v}" for p, v in punct)}<br>
-ly adverbs {fp['adverb_ly_rate']:.2%} · nominalizations {fp['nominalization_rate']:.2%} ·
passive-ish {fp['passive_rate']:.2f}/sentence</p>
{match_html}
<p class="meta">revoice — rewrite documents in your own voice</p>
</body></html>"""


def render_json(rep: dict) -> str:
    return json.dumps(rep, ensure_ascii=False, indent=2)
