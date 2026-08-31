from __future__ import annotations

import os

import httpx

from revoice.providers.base import Provider

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider(Provider):
    def complete(self, system: str, user: str) -> str:
        key = os.environ.get(self.cfg.api_key_env or "ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(f"set {self.cfg.api_key_env} for the anthropic provider")
        resp = httpx.post(
            API_URL,
            timeout=300,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.cfg.model or DEFAULT_MODEL,
                "max_tokens": self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(b["text"] for b in data["content"] if b["type"] == "text")
