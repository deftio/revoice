"""Config loading. Search order: $REVOICE_CONFIG, ./revoice.yaml, ~/.config/revoice/config.yaml."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    kind: str = "stub"  # stub | anthropic | ollama | openai_compat
    model: str = ""
    base_url: str = ""  # ollama/openai_compat
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_tokens: int = 4096
    temperature: float = 0.3


class Config(BaseModel):
    data_dir: Path = Path("data")
    # classifier: cheap-ish model for indexing; rewriter: the voice model; critic: judge only.
    classifier: ProviderConfig = Field(default_factory=ProviderConfig)
    rewriter: ProviderConfig = Field(default_factory=ProviderConfig)
    critic: ProviderConfig = Field(default_factory=ProviderConfig)


def _search_paths() -> list[Path]:
    paths = []
    if env := os.environ.get("REVOICE_CONFIG"):
        paths.append(Path(env))
    paths.append(Path("revoice.yaml"))
    paths.append(Path.home() / ".config" / "revoice" / "config.yaml")
    return paths


def load_config(explicit: Path | None = None) -> Config:
    candidates = [explicit] if explicit else _search_paths()
    for p in candidates:
        if p and p.is_file():
            raw = yaml.safe_load(p.read_text()) or {}
            cfg = Config.model_validate(raw)
            # data_dir relative to the config file's directory
            if not cfg.data_dir.is_absolute():
                cfg.data_dir = (p.parent / cfg.data_dir).resolve()
            return cfg
    return Config()
