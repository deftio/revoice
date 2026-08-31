"""Style spec: params/style.yaml — rules, phrase equivalences, weighted lexicon, hard swaps.

Division of labor (see arch doc):
  - prompt      gets rules + equivalences + QUALITATIVE lexicon rendering
  - post-pass   gets the absolutes (hard swaps) — deterministic, guaranteed
  - metrics     get the percentages (lexical conformance; future)
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

TEMPLATE = """\
# revoice style spec — edit freely; `learn` never overwrites this file once it exists.
# All sections optional.

# Explicit voice rules, injected verbatim into the rewrite prompt.
rules:
  # - "Prefer short declarative sentences after a long one."
  # - "No throat-clearing openers; start with the point."

# Phrase equivalences: preferred phrase <- list of phrases the author would replace.
# Injected as guidance; the model substitutes where natural.
phrases:
  # "In any event,": ["Now we", "Moving on,", "That said,"]

# Weighted lexicon: relative preference among synonyms (weights sum to ~1).
# Rendered QUALITATIVELY in the prompt (models can't execute probabilities);
# the numbers are used by metrics to check output distributions (future).
lexicon:
  # car: {automobile: 0.9, car: 0.09, "4 wheeler": 0.01}

# Hard swaps: ALWAYS replaced, deterministically, after the rewrite (case-preserving
# for a leading capital). Use for never-words. Keys are matched as whole words.
swaps:
  # utilize: use
  # utilizes: uses
"""


def load_style(params_dir: Path) -> dict:
    f = params_dir / "style.yaml"
    if not f.is_file():
        return {}
    data = yaml.safe_load(f.read_text()) or {}
    return {k: v for k, v in data.items() if v}


def write_template(params_dir: Path) -> bool:
    """Create the commented template if absent. Never overwrites. Returns True if created."""
    f = params_dir / "style.yaml"
    if f.is_file():
        return False
    params_dir.mkdir(parents=True, exist_ok=True)
    f.write_text(TEMPLATE)
    return True


def _qualitative(weights: dict[str, float]) -> str:
    """{automobile: .9, car: .09} -> 'prefers "automobile"; occasionally "car"'."""
    ranked = sorted(weights.items(), key=lambda kv: -float(kv[1]))
    parts = []
    for i, (word, w) in enumerate(ranked):
        w = float(w)
        if i == 0:
            parts.append(f'prefers "{word}"')
        elif w >= 0.15:
            parts.append(f'often "{word}"')
        elif w >= 0.03:
            parts.append(f'occasionally "{word}"')
        else:
            parts.append(f'rarely "{word}"')
    return "; ".join(parts)


def render_prompt_section(style: dict) -> str:
    """Render the style spec for injection into REWRITE_SYSTEM. Empty string if no spec."""
    lines: list[str] = []
    if rules := style.get("rules"):
        lines.append("Voice rules:")
        lines += [f"- {r}" for r in rules]
    if phrases := style.get("phrases"):
        lines.append("Phrase preferences (substitute where natural):")
        lines += [f'- say "{pref}" rather than: ' + ", ".join(f'"{a}"' for a in alts)
                  for pref, alts in phrases.items()]
    if lexicon := style.get("lexicon"):
        lines.append("Word choices:")
        lines += [f"- for '{concept}': {_qualitative(w)}" for concept, w in lexicon.items()]
    return "\n".join(lines)


def apply_hard_swaps(text: str, style: dict) -> tuple[str, list[str]]:
    """Deterministic whole-word swaps. Returns (text, list of applied 'a->b')."""
    applied = []
    for src, dst in (style.get("swaps") or {}).items():
        rx = re.compile(rf"\b{re.escape(str(src))}\b", re.IGNORECASE)

        def _sub(m, dst=str(dst)):
            w = m.group(0)
            return dst[0].upper() + dst[1:] if w[0].isupper() and dst else dst

        new = rx.sub(_sub, text)
        if new != text:
            applied.append(f"{src}->{dst}")
            text = new
    return text, applied
