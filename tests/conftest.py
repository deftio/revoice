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

# A pool of sentences in ONE consistent voice. Each fixture document takes a rotating
# slice, so documents differ from each other the way a real corpus does — varied
# content, constant voice.
#
# The previous fixture was three ~30-word documents built from identical filler plus
# one varying sentence. That produced no span-level calibration bands at all, and made
# the one varying sentence score as an outlier against a baseline dominated by the
# filler. Both are artefacts no real corpus has, and both hid the attribution path.
_POOL = [
    "The oscillator drifts with temperature, and the compensation loop lags behind it.",
    "We measured the settling time across the batch and recorded the outliers separately.",
    "Ground return paths matter more than the schematic suggests.",
    "A shorter trace would reduce the coupling, though the connector placement forbids it.",
    "The regulator runs warm under load, which the enclosure does nothing to help.",
    "Bench results agreed with the model to within a few percent.",
    "Production tolerances will widen that, so the margin has to absorb it.",
    "None of this is exotic; it is ordinary discipline applied consistently.",
    "The filter rolls off earlier than the datasheet promises, and we compensated for it.",
    "Two of the boards showed the fault, and both came from the same reel.",
    "We swapped the reference and the drift halved, which settled the argument.",
    "The enclosure resonates near the switching frequency, so the mount was changed.",
    "Cable dress matters here, and the assembly drawing now says so explicitly.",
    "The supply sags during the inrush, though never far enough to trip the monitor.",
    "A second ground stitch removed the last of the coupling.",
    "The measurement jig contributed more error than the part under test.",
]


def build_learned_pack(data_dir, name="t", docs=8):
    p = VoicePack.create(data_dir, name)
    n = len(_POOL)
    for i in range(docs):
        # rotate through the pool so every document is a different selection
        picked = [_POOL[(i * 5 + k) % n] for k in range(10)]
        body = TRAIN.format(i=i) + " " + " ".join(picked)
        (p.training_dir / f"doc{i}.md").write_text(body)
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


# --- CLI/server fixtures. Here rather than in test_cli.py because more than one module
# --- now needs a working directory with a learned pack in it.
CONFIG = """data_dir: data
classifier: {kind: stub}
rewriter: {kind: stub}
critic: {kind: stub}
"""


@pytest.fixture()
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REVOICE_CONFIG", raising=False)
    (tmp_path / "revoice.yaml").write_text(CONFIG)
    return tmp_path


@pytest.fixture()
def learned_cwd(cwd):
    build_learned_pack(cwd / "data", "t")
    (cwd / "draft.md").write_text(
        "# Notes\n\ngotta fix the adc driver TODO maybe swap the opamp for one with 3 MHz bandwidth\n\n"
        "The reference must settle within 3 microseconds at 85 C.\n"
    )
    return cwd
