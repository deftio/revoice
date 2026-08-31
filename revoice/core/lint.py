"""AI-tell lint: deterministic scan for LLM tics. Runs on output (and on input via `revoice lint`).

Default patterns ship here; a voice pack can extend/override via params/lint.yaml:
  patterns:            # regex, case-insensitive
    - 'signature phrase to ban'
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_PATTERNS: list[tuple[str, str]] = [
    (r"\bdelve\b|\bdelving\b", "delve"),
    (r"\bleverag(?:e|ing|es)\b", "leverage"),
    (r"\btestament to\b", "testament-to"),
    (r"\btapestry\b", "tapestry"),
    (r"\bit'?s (?:important|worth) (?:to note|noting)\b", "important-to-note"),
    (r"\bin today'?s [a-z-]+ (?:world|landscape|environment)\b", "in-todays-world"),
    (r"\bever-evolving\b|\bfast-paced\b", "ever-evolving"),
    (r"\bseamless(?:ly)?\b", "seamless"),
    (r"\brobust\b.{0,40}\bscalable\b|\bscalable\b.{0,40}\brobust\b", "robust-scalable"),
    (r"\bunlock(?:ing)? (?:the )?(?:full )?potential\b", "unlock-potential"),
    (r"\bgame.?changer\b", "game-changer"),
    (r"\bmoreover,\b|\bfurthermore,\b", "moreover-furthermore"),
    (r"\bin conclusion\b|\bultimately,\b", "in-conclusion"),
    (r"\bnot (?:just|only) [^.,;]{2,40}[,—-] (?:but|it'?s)\b", "not-x-but-y"),
    (r"\bdive (?:deep(?:er)? )?into\b", "dive-into"),
    (r"\bnavigat(?:e|ing) the (?:complexities|landscape|challenges)\b", "navigate-complexities"),
    (r"\bplays? a (?:crucial|vital|pivotal|key) role\b", "plays-a-role"),
    (r"\bcomprehensive (?:guide|overview|solution)\b", "comprehensive-guide"),
    (r"\bwhether you'?re a\b", "whether-youre-a"),
    (r"\belevate\b|\bempower(?:s|ing)?\b", "elevate-empower"),
    (r"\bstreamlin(?:e|ed|ing)\b", "streamline"),
    (r"—[^—\n]{2,60}—[^—\n]{2,60}—", "em-dash-overuse"),
]


def load_patterns(pack_params: Path | None = None) -> list[tuple[re.Pattern, str]]:
    pats = list(DEFAULT_PATTERNS)
    if pack_params:
        f = pack_params / "lint.yaml"
        if f.is_file():
            import yaml

            extra = (yaml.safe_load(f.read_text()) or {}).get("patterns", [])
            pats += [(p, f"custom:{p[:24]}") for p in extra]
    return [(re.compile(p, re.IGNORECASE), name) for p, name in pats]


def scan(text: str, patterns) -> list[str]:
    """Return names of tells found in text."""
    return [name for rx, name in patterns if rx.search(text)]


def score(text: str, patterns) -> float:
    """Tells per 100 words — a crude AI-ification index."""
    words = max(len(re.findall(r"[a-zA-Z']+", text)), 1)
    hits = sum(len(rx.findall(text)) for rx, _ in patterns)
    return round(100 * hits / words, 2)
