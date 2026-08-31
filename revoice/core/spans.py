"""Markdown/text → spans → markdown/text. Structure is never shown to the LLM.

Block-level parse: code fences, tables, HTML blocks, and horizontal rules are PROTECTED
(byte-identical round-trip). Paragraphs, list items, blockquotes, and headings become
rewritable spans. Inline markdown (links, emphasis, code) stays inside span text; the
rewriter is instructed to preserve it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Span:
    id: str
    kind: str          # para | heading | listitem | quote | protected
    text: str          # rewritable text (without structural prefix)
    prefix: str = ""   # structural prefix to restore: "## ", "- ", "> ", indent
    raw: str = ""      # for protected blocks: the exact original lines
    meta: dict = field(default_factory=dict)


_FENCE = re.compile(r"^(\s*)(```|~~~)")
_HEADING = re.compile(r"^(#{1,6}\s+)(.*)$")
_LIST_ITEM = re.compile(r"^(\s*(?:[-*+]|\d{1,3}[.)])\s+)(.*)$")
_QUOTE = re.compile(r"^(\s*>\s?)(.*)$")
_HR = re.compile(r"^\s*([-*_]\s*){3,}$")
_TABLE = re.compile(r"^\s*\|.*\|\s*$")
_HTML = re.compile(r"^\s*<")


def parse(text: str) -> list[Span]:
    lines = text.split("\n")
    spans: list[Span] = []
    i, n = 0, len(lines)
    counter = 0

    def nid() -> str:
        nonlocal counter
        counter += 1
        return f"s{counter}"

    while i < n:
        line = lines[i]

        if not line.strip():
            spans.append(Span(nid(), "protected", "", raw=line))
            i += 1
            continue

        m = _FENCE.match(line)
        if m:  # code fence — protect until closing fence
            fence = m.group(2)
            block = [line]
            i += 1
            while i < n:
                block.append(lines[i])
                if lines[i].strip().startswith(fence):
                    i += 1
                    break
                i += 1
            spans.append(Span(nid(), "protected", "", raw="\n".join(block)))
            continue

        if _HR.match(line) or _TABLE.match(line) or _HTML.match(line):
            spans.append(Span(nid(), "protected", "", raw=line))
            i += 1
            continue

        m = _HEADING.match(line)
        if m:
            spans.append(Span(nid(), "heading", m.group(2), prefix=m.group(1)))
            i += 1
            continue

        m = _LIST_ITEM.match(line)
        if m:  # list item + its continuation lines
            prefix, first = m.group(1), m.group(2)
            body = [first]
            i += 1
            cont_indent = " " * len(prefix)
            while (i < n and lines[i].strip() and not _LIST_ITEM.match(lines[i])
                   and lines[i].startswith((cont_indent, "\t"))):
                body.append(lines[i].strip())
                i += 1
            spans.append(Span(nid(), "listitem", " ".join(body), prefix=prefix))
            continue

        m = _QUOTE.match(line)
        if m:
            body = [m.group(2)]
            i += 1
            while i < n and (q := _QUOTE.match(lines[i])):
                body.append(q.group(2))
                i += 1
            spans.append(Span(nid(), "quote", " ".join(b for b in body if b), prefix="> "))
            continue

        # paragraph: consume until blank line or structural line
        body = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not (
            _FENCE.match(lines[i]) or _HEADING.match(lines[i]) or _LIST_ITEM.match(lines[i])
            or _QUOTE.match(lines[i]) or _HR.match(lines[i]) or _TABLE.match(lines[i]) or _HTML.match(lines[i])
        ):
            body.append(lines[i].strip())
            i += 1
        spans.append(Span(nid(), "para", " ".join(body)))

    return spans


def reassemble(spans: list[Span], width: int = 0) -> str:
    """Spans back to text. width=0 → one line per paragraph (no re-wrapping)."""
    out = []
    for s in spans:
        if s.kind == "protected":
            out.append(s.raw)
        elif s.kind == "quote":
            out.append("\n".join(f"> {ln}" if ln else ">" for ln in [s.text]))
        else:
            out.append(f"{s.prefix}{s.text}")
    return "\n".join(out)


def rewritable(spans: list[Span]) -> list[Span]:
    return [s for s in spans if s.kind in ("para", "listitem", "quote") and s.text.strip()]
