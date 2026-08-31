"""Shared fixtures: a learned stub voice pack + fake providers."""

from __future__ import annotations

import pytest

from revoice.config import ProviderConfig
from revoice.core.indexer import index_corpus
from revoice.core.metrics import build_baselines
from revoice.core.profiles import build_profiles
from revoice.core.voicepack import VoicePack
from revoice.providers import make_provider
from revoice.providers.base import Provider

TRAIN = (
    "The impedance matching network transforms the antenna load. "
    "Component tolerances dominate the error budget, so we specified precision parts. "
    "Layout discipline keeps the noise floor low in revision {i}."
)


def build_learned_pack(data_dir, name="t"):
    p = VoicePack.create(data_dir, name)
    for i in range(3):
        (p.training_dir / f"doc{i}.md").write_text(TRAIN.format(i=i))
    stub = make_provider(ProviderConfig(kind="stub"))
    index_corpus(p, stub)
    build_profiles(p, stub)
    build_baselines(p)
    return p


@pytest.fixture()
def learned_pack(tmp_path):
    return build_learned_pack(tmp_path / "data")


class FakeProvider(Provider):
    """complete() delegates to fn(system, user, call_number)."""

    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.fn(system, user, len(self.calls))


@pytest.fixture()
def stub():
    return make_provider(ProviderConfig(kind="stub"))
