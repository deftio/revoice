from __future__ import annotations

import json

from revoice.providers.base import Provider


class StubProvider(Provider):
    """Deterministic offline provider so the pipeline runs with no LLM. For tests/smoke only."""

    def complete(self, system: str, user: str) -> str:
        if "CLASSIFY_DOC" in system:
            # crude heuristics so smoke tests exercise real branching
            lower = user.lower()
            register = "fiction" if ("once upon" in lower or "she said" in lower) else "professional"
            polish = "brain_dump" if ("todo" in lower or "???" in lower or "gotta" in lower) else "polished"
            return json.dumps(
                {
                    "register": register,
                    "polish": polish,
                    "domains": ["general"],
                    "summary": user.strip().splitlines()[0][:80] if user.strip() else "",
                    "confidence": 0.5,
                }
            )
        if "BUILD_PROFILE" in system:
            return json.dumps(
                {
                    "voice_summary": "[stub profile — run with a real provider]",
                    "sentence_rhythm": "",
                    "vocabulary": "",
                    "habits": "",
                    "never_does": "",
                }
            )
        if "You are a test" in system:
            return '{"ok": true, "who": "stub"}'
        if "RUBRIC_JUDGE" in system:
            # deterministically answer the first (best) choice listed
            import re

            m = re.search(r"^- ([a-z_]+):", system, re.MULTILINE)
            return m.group(1) if m else "unknown"
        if "COHESION_EDIT" in system:
            return user  # stub: span always reads fine in context
        if "REWRITE_SPAN" in system:
            # deterministic mock rewrite: de-slang + tidy, numbers/names untouched
            out = user.split("SPAN TO REWRITE:\n", 1)[-1]
            for a, b in [("gotta", "need to"), ("???", "?"), ("TODO", "to do:"),
                         ("maybe", "perhaps"), ("stuff", "material")]:
                out = out.replace(a, b)
            out = out.strip()
            if out and out[0].islower():
                out = out[0].upper() + out[1:]
            if out and out[-1] not in ".!?":
                out += "."
            return out
        return "[stub completion]"
