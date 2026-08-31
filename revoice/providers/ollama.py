from __future__ import annotations

import httpx

from revoice.providers.base import Provider

DEFAULT_URL = "http://localhost:11434"


class OllamaProvider(Provider):
    def complete(self, system: str, user: str) -> str:
        base = (self.cfg.base_url or DEFAULT_URL).rstrip("/")
        resp = httpx.post(
            f"{base}/api/chat",
            timeout=600,
            json={
                "model": self.cfg.model or "gemma3:27b",
                "stream": False,
                "think": False,  # suppress qwen3-style reasoning traces (ignored by non-thinking models)
                "options": {"temperature": self.cfg.temperature, "num_predict": self.cfg.max_tokens},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
