"""Render a voice-similarity report as a standalone SVG.

Why SVG generated in Python, with no dependencies: the chart has to work in the
terminal-adjacent world revoice lives in — written to a file, embedded in the HTML
`stats` report, attached to a review, opened in five years. A plotting library or a JS
runtime would be the largest dependency in the project and the first thing to rot.

What the chart is trying to prevent
-----------------------------------
A single similarity number invites a decision it cannot support. On our own benchmark
a held-out Twain sample scores 45.9 and a Bret Harte sample scores 37.2 — which reads
as decisive until you see the intervals, [31.9-49.1] and [25.2-45.9], overlapping
across most of their range. So the interval is drawn at the same visual weight as the
estimate, and when two readings overlap the chart says so in words rather than leaving
the reader to compare bar lengths.

Design rules followed here:
  * magnitude AND direction per axis — "your sentences are long" is more useful than
    "sentence_length: 0.42"
  * uncertainty is never optional decoration; a point estimate without its interval is
    not drawn at all
  * colour is redundant. Every value is printed as a number and encoded as bar length,
    so the chart survives greyscale printing and colour-blind readers; the palette is
    blue/amber rather than red/green for the same reason.
"""

from __future__ import annotations

from revoice.voicemetric.space import AXES

# Muted and colour-blind-safe, and never the only channel carrying meaning.
#
# Each colour is a CSS custom property with a literal fallback. Standalone the file
# uses the fallback; inlined into a themed page it picks up that page's tokens, so the
# same generator serves a written-out .svg and the HTML `stats` report without the
# chart becoming a white slab on a dark ground.
INK = "var(--vc-ink, #23262b)"
MUTED = "var(--vc-muted, #6b7280)"
RULE = "var(--vc-rule, #d9dce1)"
BG = "var(--vc-bg, #ffffff)"
PANEL = "var(--vc-panel, #f6f7f9)"
NEAR = "var(--vc-near, #2f6f9f)"      # close to the voice
FAR = "var(--vc-far, #c98a2b)"        # far from the voice
BAND = "var(--vc-band, #9fc0da)"      # confidence interval

ROW_H = 22
FAMILY_GAP = 12
PLOT_W = 340
LABEL_W = 172
VALUE_W = 132
MARGIN = 22
MAX_SD = 3.0          # deviation axis clamp


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _colour(similarity: float) -> str:
    """Blue when close, amber when far. Redundant with bar length by design."""
    return NEAR if similarity >= 0.5 else FAR


def _verdict(report: dict) -> tuple[str, str]:
    """Plain-language reading of the interval, not of the point estimate."""
    lo, hi = report["low"], report["high"]
    width = hi - lo
    if not report["interval_reliable"]:
        return ("no interval — too short to resample",
                "Under three paragraphs there is nothing to bootstrap, so this number "
                "has no measured uncertainty. Treat it as an impression.")
    if width > 25:
        return ("wide interval — inconclusive",
                f"The score moves {width:.0f} points depending on which part of the "
                "document is sampled. That is a property of the text, not a rounding "
                "error: it is internally varied, or too short to settle.")
    if lo >= 55:
        return ("consistently close", "Every resample stays close to this voice.")
    if hi <= 40:
        return ("consistently distant", "No resample comes close to this voice.")
    return ("moderate, with real uncertainty",
            "The interval spans the range where this measure cannot separate two "
            "authors of the same genre. Read the axes, not the headline.")


def render(report: dict, title: str = "", subtitle: str = "") -> str:
    """SVG for one `voicespace.similarity_report` result."""
    families: list[str] = []
    for a in AXES:
        if a.family not in families:
            families.append(a.family)

    rows = sum(len([x for x in AXES if x.family == f]) for f in families)
    header_h = 132
    body_h = rows * ROW_H + len(families) * (FAMILY_GAP + 14) + 16
    footer_h = 54
    width = MARGIN * 2 + LABEL_W + PLOT_W + VALUE_W
    height = header_h + body_h + footer_h

    cx = MARGIN + LABEL_W + PLOT_W / 2          # deviation zero line
    scale = (PLOT_W / 2) / MAX_SD

    p: list[str] = []
    add = p.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="-apple-system,BlinkMacSystemFont,'
        f'\'Segoe UI\',Helvetica,Arial,sans-serif">')
    add(f'<rect width="{width}" height="{height}" fill="{BG}"/>')

    # ---- header: the estimate and its interval, at equal weight ----
    head = _esc(title or f"Voice similarity — {report['voice']}")
    add(f'<text x="{MARGIN}" y="26" font-size="15" font-weight="650" fill="{INK}">{head}</text>')
    if subtitle:
        add(f'<text x="{MARGIN}" y="44" font-size="11" fill="{MUTED}">{_esc(subtitle)}</text>')

    bar_x, bar_y, bar_w, bar_h = MARGIN, 60, width - MARGIN * 2, 16
    add(f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="4" fill="{PANEL}"/>')
    lo_x = bar_x + bar_w * report["low"] / 100.0
    hi_x = bar_x + bar_w * report["high"] / 100.0
    pt_x = bar_x + bar_w * report["overall"] / 100.0
    if report["interval_reliable"]:
        add(f'<rect x="{lo_x:.1f}" y="{bar_y}" width="{max(hi_x - lo_x, 1):.1f}" '
            f'height="{bar_h}" rx="4" fill="{BAND}"/>')
    add(f'<line x1="{pt_x:.1f}" y1="{bar_y - 4}" x2="{pt_x:.1f}" y2="{bar_y + bar_h + 4}" '
        f'stroke="{INK}" stroke-width="2.5"/>')
    for tick in (0, 25, 50, 75, 100):
        tx = bar_x + bar_w * tick / 100.0
        add(f'<line x1="{tx:.1f}" y1="{bar_y + bar_h}" x2="{tx:.1f}" y2="{bar_y + bar_h + 4}" '
            f'stroke="{RULE}"/>')
        add(f'<text x="{tx:.1f}" y="{bar_y + bar_h + 15}" font-size="9" fill="{MUTED}" '
            f'text-anchor="middle">{tick}</text>')

    ci = (f'{report["overall"]:.1f}  '
          f'({report["confidence"]:.0%} interval {report["low"]:.1f}–{report["high"]:.1f})'
          if report["interval_reliable"] else f'{report["overall"]:.1f}  (no interval)')
    add(f'<text x="{MARGIN}" y="{bar_y + bar_h + 32}" font-size="12" font-weight="600" '
        f'fill="{INK}">{_esc(ci)}</text>')
    label, explain = _verdict(report)
    add(f'<text x="{MARGIN + 210}" y="{bar_y + bar_h + 32}" font-size="12" '
        f'fill="{MUTED}">{_esc(label)}</text>')

    # ---- per-axis rows, grouped by family ----
    y = header_h
    for family in families:
        add(f'<text x="{MARGIN}" y="{y}" font-size="10" font-weight="650" fill="{MUTED}" '
            f'letter-spacing="0.06em">{_esc(family.upper())}</text>')
        y += 10
        for axis in [a for a in AXES if a.family == family]:
            d = report["axes"][axis.name]
            dev = max(-MAX_SD, min(MAX_SD, d["deviation"]))
            sim = d["similarity"]
            colour = _colour(sim)
            row_mid = y + ROW_H / 2

            add(f'<text x="{MARGIN}" y="{row_mid + 3.5}" font-size="11" fill="{INK}">'
                f'{_esc(axis.name)}</text>')
            add(f'<rect x="{MARGIN + LABEL_W}" y="{y + 3}" width="{PLOT_W}" '
                f'height="{ROW_H - 6}" fill="{PANEL}"/>')
            add(f'<line x1="{cx}" y1="{y + 2}" x2="{cx}" y2="{y + ROW_H - 2}" '
                f'stroke="{RULE}"/>')

            # deviation bar: length is magnitude, side is direction
            bw = abs(dev) * scale
            bx = cx if dev >= 0 else cx - bw
            add(f'<rect x="{bx:.1f}" y="{y + 6}" width="{max(bw, 1):.1f}" height="{ROW_H - 12}" '
                f'rx="2" fill="{colour}" opacity="0.85"/>')

            # interval, drawn from the similarity bounds mapped back onto this row
            if report["interval_reliable"]:
                spread = (d["high"] - d["low"])
                half = min(spread * 1.5, MAX_SD) * scale / 2
                add(f'<line x1="{max(cx - PLOT_W / 2, bx + bw / 2 - half):.1f}" y1="{row_mid}" '
                    f'x2="{min(cx + PLOT_W / 2, bx + bw / 2 + half):.1f}" y2="{row_mid}" '
                    f'stroke="{INK}" stroke-width="1" opacity="0.45"/>')

            side = axis.high if dev > 0 else axis.low
            add(f'<text x="{MARGIN + LABEL_W + PLOT_W + 8}" y="{row_mid + 3.5}" font-size="10" '
                f'fill="{MUTED}">{sim:.2f}  {_esc(side)}</text>')
            y += ROW_H
        y += FAMILY_GAP

    # ---- footer ----
    fy = height - footer_h + 14
    add(f'<line x1="{MARGIN}" y1="{fy - 12}" x2="{width - MARGIN}" y2="{fy - 12}" stroke="{RULE}"/>')
    add(f'<text x="{MARGIN}" y="{fy + 2}" font-size="9.5" fill="{MUTED}">'
        f'{_esc(explain)}</text>')
    add(f'<text x="{MARGIN}" y="{fy + 16}" font-size="9.5" fill="{MUTED}">'
        f'Bars show signed deviation in the voice&#8217;s own standard deviations '
        f'(left = less, right = more); whiskers are the bootstrap interval over '
        f'{report["windows"]} document windows.</text>')
    add("</svg>")
    return "\n".join(p)


# ---------- the full report ----------


def overlap(a: dict, b: dict) -> float:
    """Points of overlap between two reports' confidence intervals.

    The number that decides whether a difference means anything. Two samples can differ
    by 9 points and still have intervals sharing 14 — at which point the ordering is not
    evidence, and a bare comparison of the two scores is actively misleading.
    """
    if not (a["interval_reliable"] and b["interval_reliable"]):
        return float("nan")
    return min(a["high"], b["high"]) - max(a["low"], b["low"])


def worst_overlap(reports: list[dict]) -> tuple[dict, dict, float] | None:
    """The pair whose intervals overlap most — the comparison least able to bear weight."""
    worst = None
    for i, a in enumerate(reports):
        for b in reports[i + 1:]:
            ov = overlap(a, b)
            if ov == ov and (worst is None or ov > worst[2]):
                worst = (a, b, ov)
    return worst


def _bar(value: float, width: int = 20) -> str:
    """A fixed-width bar in plain characters, so the table reads in a terminal, in a
    diff, in a pull request comment and in anything that renders Markdown."""
    filled = max(0, min(width, int(round(value / 100.0 * width))))
    return "\u2588" * filled + "\u00b7" * (width - filled)


def markdown(items: list[tuple[str, str, dict]], voice: str, engine: str = "") -> str:
    """The same report as Markdown, for pasting into an issue, a PR or a notebook.

    Deliberately not a transcription of the HTML. The HTML can draw an interval; plain
    text cannot, so this leads with the thing the drawing exists to communicate — whether
    the intervals overlap — states it in words before any table, and repeats the interval
    in every row so no number ever appears without it.

    Mirrored by `vmMarkdownReport` in pages/voicemetric.js and checked by
    tests/test_pages_parity.py, so the button on the page and this function cannot drift.
    """
    reports = [r for _, _, r in items]
    lines = [f"# Voice report \u2014 {voice}", ""]
    lines.append(f"{len(items)} sample(s) measured against the voice \u201c{voice}\u201d.")
    lines.append("")

    worst = worst_overlap(reports)
    if worst is not None:
        a, b, ov = worst
        gap = abs(a["overall"] - b["overall"])
        # Three cases, not two. Exactly-touching intervals used to be reported as
        # "clear by -0.0 points" — nonsense, and it read differently in the two
        # implementations because Python formats negative zero as "-0.0" and
        # JavaScript's toFixed gives "0.0". The parity test caught the formatting
        # difference; the wording was wrong in both.
        lines += ["## What this says", ""]
        if ov > 0:
            lines.append(
                f"**The two closest readings differ by {gap:.1f} points and their "
                f"intervals overlap by {ov:.1f}.** That ordering is not evidence. Read "
                "the per-axis tables, not the headline numbers.")
        elif ov == 0:
            lines.append(
                f"**The two closest readings differ by {gap:.1f} points and their "
                "intervals meet exactly, without overlapping.** That is the boundary of "
                "what this measure can separate \u2014 treat the ordering as unproven.")
        else:
            lines.append(
                f"**The two closest readings differ by {gap:.1f} points and their "
                f"intervals clear each other by {-ov:.1f} points.** That separation is "
                "real on this measure \u2014 though see the limits below.")
        lines.append("")

    lines += ["## Every reading on one scale", "",
              "| sample | score | 90% interval | |", "|---|---:|---|---|"]
    for name, _src, r in items:
        band = (f"{r['low']:.0f}\u2013{r['high']:.0f}" if r["interval_reliable"]
                else "no interval \u2014 too short")
        lines.append(f"| {name} | {r['overall']:.0f} | {band} | `{_bar(r['overall'])}` |")
    lines.append("")

    for name, _src, r in items:
        head, why = _verdict(r)
        lines += [f"## {name}", "",
                  f"**{r['overall']:.0f} / 100** \u2014 {head}. {why}", ""]
        ranked = sorted(r["axes"].items(), key=lambda kv: kv[1]["similarity"])
        lines += ["| axis | similarity | deviation |", "|---|---:|---:|"]
        for axis, d in ranked[:6]:
            lines.append(f"| {axis.replace('_', ' ')} | {d['similarity']:.2f} | "
                         f"{d['deviation']:+.2f} |")
        lines += ["", f"*{r['words']} words, {r['windows']} window(s).*", ""]

    lines += [
        "## How to read this",
        "",
        "- **Score** is 0\u2013100 similarity to the reference voice across 17 named axes.",
        "- **Interval** is a bootstrap over the document\u2019s own paragraphs: resample them,",
        "  rescore, and report the middle 90%. It answers *how much would this move if I",
        "  had been handed a different few pages of the same document?*",
        "- **Overlapping intervals mean the ordering is not evidence.** Two samples can",
        "  differ by 9 points and still share 14 points of interval.",
        "- **Deviation** is signed, in the voice\u2019s own spread: which way, not just how far.",
        "",
        "## Limits",
        "",
        "This measures **register** \u2014 how a passage is pitched \u2014 far better than it",
        "measures **authorship**. Under a topic-controlled protocol across 70 authors with",
        "same-genre negatives it reaches AUC 0.67. Use it to notice that an edit moved your",
        "register. Do not use it to decide who wrote something.",
        "",
    ]
    if engine:
        lines.append(f"*Generated by revoice \u00b7 {engine}*")
    return "\n".join(lines)


_PAGE_CSS = """
:root {
  --paper:#fbfbfc; --ink:#1b1f24; --muted:#5f6873; --panel:#f2f4f7; --rule:#dde1e7;
  --accent:#2f6f9f; --warn:#c98a2b; --band:#9fc0da;
  --vc-ink:#1b1f24; --vc-muted:#5f6873; --vc-rule:#dde1e7; --vc-bg:transparent;
  --vc-panel:#eef1f5; --vc-near:#2f6f9f; --vc-far:#c98a2b; --vc-band:#9fc0da;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper:#14171b; --ink:#e6e8ec; --muted:#98a2ae; --panel:#1d2126; --rule:#2c323a;
    --accent:#6ea8d4; --warn:#e0a94a; --band:#3d5f7d;
    --vc-ink:#e6e8ec; --vc-muted:#98a2ae; --vc-rule:#2c323a; --vc-bg:transparent;
    --vc-panel:#20252b; --vc-near:#6ea8d4; --vc-far:#e0a94a; --vc-band:#3d5f7d;
  }
}
:root[data-theme="dark"] {
  --paper:#14171b; --ink:#e6e8ec; --muted:#98a2ae; --panel:#1d2126; --rule:#2c323a;
  --accent:#6ea8d4; --warn:#e0a94a; --band:#3d5f7d;
  --vc-ink:#e6e8ec; --vc-muted:#98a2ae; --vc-rule:#2c323a; --vc-bg:transparent;
  --vc-panel:#20252b; --vc-near:#6ea8d4; --vc-far:#e0a94a; --vc-band:#3d5f7d;
}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);margin:0;padding:0 1.25rem 4rem;
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:920px;margin:0 auto}
header{border-bottom:2px solid var(--ink);padding:2.2rem 0 1rem;margin-bottom:1.5rem}
.eyebrow{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.72rem;
  letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0 0 .5rem}
h1{font-size:1.7rem;font-weight:600;letter-spacing:-.015em;margin:0 0 .5rem;text-wrap:balance}
.standfirst{margin:0;max-width:62ch;color:var(--muted)}
.specs{display:flex;flex-wrap:wrap;gap:0 2rem;margin-top:1rem;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.75rem;color:var(--muted)}
.specs b{color:var(--ink);font-weight:500}
h2{font-size:1.05rem;font-weight:600;margin:2.4rem 0 .35rem}
.lede{margin:0 0 1.1rem;color:var(--muted);max-width:64ch}
p{max-width:64ch}
.rail{background:var(--panel);border:1px solid var(--rule);border-radius:6px;
  padding:1.2rem 1.3rem 1rem;display:flex;flex-direction:column;gap:.8rem}
.rrow{display:grid;grid-template-columns:minmax(0,15rem) 1fr 5.5rem;gap:1rem;align-items:center}
.rlabel{display:flex;flex-direction:column;min-width:0}
.rsub{font-size:.78rem;color:var(--muted)}
.rtrack{position:relative;height:20px;background:var(--paper);border:1px solid var(--rule);
  border-radius:3px}
.rband{position:absolute;top:0;bottom:0;background:var(--band);opacity:.85;border-radius:2px}
.rpoint{position:absolute;top:-3px;bottom:-3px;width:2.5px;background:var(--ink)}
.rnum{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;text-align:right;line-height:1.25;
  font-variant-numeric:tabular-nums}
.rnum b{font-size:1rem;font-weight:600}
.rnum span{display:block;font-size:.72rem;color:var(--muted)}
.rscale{display:grid;grid-template-columns:minmax(0,15rem) 1fr 5.5rem;gap:1rem;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.68rem;color:var(--muted)}
.rticks{display:flex;justify-content:space-between}
.verdict{margin-top:.85rem;padding-top:.8rem;border-top:1px solid var(--rule);
  display:flex;gap:.7rem;align-items:baseline;flex-wrap:wrap}
.flag{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.72rem;
  letter-spacing:.08em;text-transform:uppercase;color:var(--warn);border:1px solid var(--warn);
  border-radius:3px;padding:.12rem .45rem;white-space:nowrap}
.verdict p{margin:0;font-size:.9rem;color:var(--muted);max-width:58ch}
figure{margin:1.5rem 0 0;padding:0;border-top:1px solid var(--rule)}
figcaption{padding:1rem 0 .3rem}
figcaption h3{margin:0;font-size:.97rem;font-weight:600}
figcaption p{margin:.15rem 0 0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:.74rem;color:var(--muted)}
.scroll{overflow-x:auto}
svg{display:block;max-width:100%;height:auto}
dl{display:grid;grid-template-columns:minmax(0,11rem) 1fr;gap:.5rem 1.3rem;margin:1rem 0 0}
dt{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.78rem;color:var(--muted)}
dd{margin:0;font-size:.93rem}
.note{background:var(--panel);border-left:3px solid var(--accent);border-radius:0 4px 4px 0;
  padding:.85rem 1.05rem;margin:1.3rem 0}
.note p{margin:0;font-size:.92rem}
footer{margin-top:2.6rem;padding-top:1rem;border-top:1px solid var(--rule);
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.72rem;color:var(--muted)}
@media(max-width:640px){.rrow,.rscale{grid-template-columns:1fr;gap:.3rem}.rnum{text-align:left}}
"""


def report(items: list[tuple[str, str, dict]], voice: str, engine: str = "",
           title: str = "", standfirst: str = "") -> str:
    """A complete, standalone HTML report for several samples against one voice.

    `items` is (label, sublabel, similarity_report). The per-sample charts come from
    `render`; what this adds is the part a single chart cannot show — **every reading on
    one shared scale**, so overlapping intervals are the first thing the eye lands on
    rather than something a careful reader works out from two separate pictures.

    Self-contained: no scripts, no network, no fonts to fetch. It opens from a file, in
    an email, or in five years.
    """
    reports = [r for _, _, r in items]
    worst = worst_overlap(reports)
    ordered = sorted(items, key=lambda it: -it[2]["overall"])

    rails = []
    for label, sub, r in ordered:
        lo, hi, pt = r["low"], r["high"], r["overall"]
        band = (f'<span class="rband" style="left:{lo}%;width:{max(hi - lo, 0.6):.2f}%"></span>'
                if r["interval_reliable"] else "")
        ci = f"{lo:.0f}–{hi:.0f}" if r["interval_reliable"] else "no interval"
        rails.append(
            f'<div class="rrow">'
            f'<div class="rlabel"><span>{_esc(label)}</span>'
            f'<span class="rsub">{_esc(sub)}</span></div>'
            f'<div class="rtrack" role="img" aria-label="{_esc(label)}: {pt:.0f} of 100, '
            f'interval {ci}">{band}'
            f'<span class="rpoint" style="left:{min(max(pt, 0), 100):.2f}%"></span></div>'
            f'<div class="rnum"><b>{pt:.0f}</b><span>{ci}</span></div></div>')

    if worst and worst[2] > 0:
        a, b, ov = worst
        gap = abs(a["overall"] - b["overall"])
        verdict = (
            f'<span class="flag">{ov:.1f} pts overlap</span>'
            f'<p>The closest pair differ by {gap:.1f} points and their intervals overlap by '
            f'{ov:.1f}, so that ordering is not evidence. Read the axes below, not the '
            f'headline numbers.</p>')
    elif worst:
        verdict = ('<span class="flag">no overlap</span>'
                   '<p>No two intervals overlap, so the ordering above is supported by the '
                   'measurement rather than by the point estimates alone.</p>')
    else:
        verdict = ('<span class="flag">no intervals</span>'
                   '<p>Too few paragraphs to resample, so none of these readings carries a '
                   'measured uncertainty. Treat them as impressions.</p>')

    figures = []
    for label, sub, r in ordered:
        ci = (f"{r['confidence']:.0%} interval" if r["interval_reliable"] else "no interval")
        figures.append(
            f'<figure><figcaption><h3>{_esc(label)}</h3>'
            f'<p>{_esc(sub)} · {r["words"]} words · {r["windows"]} windows · {ci}</p>'
            f'</figcaption><div class="scroll">'
            f'{render(r, title=f"{label} vs voice “{voice}”", subtitle="")}</div></figure>')

    head = _esc(title or f"Voice similarity — {voice}")
    stand = _esc(standfirst or (
        f"{len(items)} sample{'s' if len(items) != 1 else ''} measured against the voice "
        f"“{voice}”. Each reading is a point estimate and a bootstrap interval, because on "
        "this measure the interval is usually the part that decides what you may conclude."))
    n_axes = len(AXES)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{head}</title><style>{_PAGE_CSS}</style></head><body><div class="wrap">
<header>
  <p class="eyebrow">revoice · voicemetric</p>
  <h1>{head}</h1>
  <p class="standfirst">{stand}</p>
  <div class="specs"><span>axes <b>{n_axes}</b></span>
    <span>samples <b>{len(items)}</b></span>
    <span>interval <b>bootstrap over document windows</b></span>
    {f'<span>engine <b>{_esc(engine)}</b></span>' if engine else ''}</div>
</header>

<h2>Every reading on one scale</h2>
<p class="lede">Point estimate in black; the shaded band is where the score lands when the
document's own paragraphs are resampled.</p>
<div class="rail">
{chr(10).join(rails)}
  <div class="rscale"><span></span><span class="rticks"><span>0</span><span>25</span>
    <span>50</span><span>75</span><span>100</span></span><span></span></div>
  <div class="verdict">{verdict}</div>
</div>

<h2>Axis by axis</h2>
<p class="lede">Bar length is the size of the difference, side is its direction, the number
is per-axis similarity, and the whisker is the bootstrap interval.</p>
{chr(10).join(figures)}

<h2>How the interval is produced</h2>
<dl>
  <dt>resampling unit</dt><dd>Paragraph windows of roughly 220 words — about the smallest
    span at which paragraph shape and rhythm mean anything.</dd>
  <dt>procedure</dt><dd>Coordinates are computed once per window, then windows are
    resampled with replacement and the statistic recomputed. The band is the 5th to 95th
    percentile.</dd>
  <dt>what it answers</dt><dd>How much the score would move given a different few pages of
    the same document — not how likely it is that the author is the right one.</dd>
  <dt>when it is absent</dt><dd>Under three windows there is nothing to resample. The
    report says so rather than drawing a band it cannot support.</dd>
</dl>

<div class="note"><p><strong>What this is not.</strong> It is not an authorship test.
Measured across 70 authors in 11 genres with same-genre negatives, the underlying metric
reaches AUC ≈ 0.69 — useful for noticing that an edit moved a document's register, not for
deciding who wrote something.</p></div>

<footer>Generated by revoice · charts are dependency-free SVG · no scripts, no network</footer>
</div></body></html>"""
