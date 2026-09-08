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
