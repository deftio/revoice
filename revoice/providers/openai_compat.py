from __future__ import annotations

import os

import httpx

from revoice.providers.base import Provider


class OpenAICompatProvider(Provider):
    """Any OpenAI-compatible endpoint: llama.cpp server, LM Studio, mlx_lm.server, vLLM, OpenAI."""

    def complete(self, system: str, user: str) -> str:
        base = (self.cfg.base_url or "http://localhost:8080/v1").rstrip("/")
        headers = {"content-type": "application/json"}
        if key := os.environ.get(self.cfg.api_key_env or "", ""):
            headers["authorization"] = f"Bearer {key}"
        resp = httpx.post(
            f"{base}/chat/completions",
            timeout=600,
            headers=headers,
            json={
                "model": self.cfg.model,
                "max_tokens": self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "messages": [
                    # /no_think: qwen3-family soft switch; inert text for other models
                    {"role": "system", "content": system + "\n/no_think"},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
