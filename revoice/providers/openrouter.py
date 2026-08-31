from __future__ import annotations

import os

import httpx

from revoice.providers.base import Provider

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(Provider):
    """OpenRouter — one key, any hosted model ("anthropic/claude-sonnet-5",
    "google/gemma-3-27b-it", "qwen/qwen3.5-122b-a10b", ...). Needs OPENROUTER_API_KEY."""

    def complete(self, system: str, user: str) -> str:
        key = os.environ.get(self.cfg.api_key_env or "OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError(f"set {self.cfg.api_key_env or 'OPENROUTER_API_KEY'} for the openrouter provider")
        resp = httpx.post(
            self.cfg.base_url or API_URL,
            timeout=600,
            headers={
                "authorization": f"Bearer {key}",
                "content-type": "application/json",
                "x-title": "revoice",
            },
            json={
                "model": self.cfg.model,
                "reasoning": {"enabled": False},  # no thinking traces
                "max_tokens": self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
