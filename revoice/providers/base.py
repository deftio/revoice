from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from revoice.config import ProviderConfig


class Provider(ABC):
    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """One-shot completion. Returns raw text."""

    def complete_json(self, system: str, user: str) -> dict | list:
        """Completion that must yield JSON. Extracts the first JSON object/array from the reply."""
        text = self.complete(system + "\nRespond with valid JSON only.", user)
        return extract_json(text)


def extract_json(text: str):
    # strip reasoning traces (qwen3 etc.) before hunting for JSON
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"^.*?</think>", "", text, flags=re.DOTALL)  # unclosed-open variant
    text = text.strip()
    # strip markdown fences
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # first { ... } or [ ... ] span
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    raise ValueError(f"no JSON found in model output: {text[:200]!r}")
