from __future__ import annotations

from revoice.config import ProviderConfig
from revoice.providers.base import Provider


def make_provider(cfg: ProviderConfig) -> Provider:
    if cfg.kind == "stub":
        from revoice.providers.stub import StubProvider

        return StubProvider(cfg)
    if cfg.kind == "anthropic":
        from revoice.providers.anthropic import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.kind == "ollama":
        from revoice.providers.ollama import OllamaProvider

        return OllamaProvider(cfg)
    if cfg.kind == "openrouter":
        from revoice.providers.openrouter import OpenRouterProvider

        return OpenRouterProvider(cfg)
    if cfg.kind == "openai_compat":
        from revoice.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(cfg)
    raise ValueError(f"unknown provider kind: {cfg.kind}")
