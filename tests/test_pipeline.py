"""End-to-end with the stub provider: learn a tiny voice, revoice a doc, check invariants."""

import json

import pytest

from revoice.config import ProviderConfig
from revoice.core.indexer import index_corpus
from revoice.core.metrics import build_baselines
from revoice.core.pipeline import revoice_document
from revoice.core.profiles import build_profiles
from revoice.core.voicepack import VoicePack
from revoice.providers import make_provider

DOC = """# Notes

gotta fix the adc driver TODO maybe swap the opamp for one with 3 MHz bandwidth

```py
x = 42  # gotta leave this
```

The reference must settle within 3 microseconds at 85 C.
"""


@pytest.fixture()
def pack(tmp_path):
    p = VoicePack.create(tmp_path / "data", "t")
    for i in range(3):
        (p.training_dir / f"doc{i}.md").write_text(
            "The impedance matching network transforms the antenna load. "
            "Component tolerances dominate the error budget, so we specified precision parts. "
            f"Layout discipline keeps the noise floor low in revision {i}."
        )
    stub = make_provider(ProviderConfig(kind="stub"))
    index_corpus(p, stub)
    build_profiles(p, stub)
    build_baselines(p)
    return p


def test_revoice_invariants(pack):
    stub = make_provider(ProviderConfig(kind="stub"))
    out, report = revoice_document(DOC, pack, stub, strength=0.7)
    # structure preserved
    assert "# Notes" in out
    assert "x = 42  # gotta leave this" in out          # code untouched
    # numbers preserved in rewritten spans
    assert "3 MHz" in out and "85 C" in out and "3 microseconds" in out
    # diff report shape
    assert report["summary"]["error"] == 0
    assert all(s["status"] in ("rewritten", "unchanged") or "kept-original" in s["status"]
               for s in report["spans"])
    json.dumps(report)  # serializable


def test_strength_zero_is_conservative(pack):
    stub = make_provider(ProviderConfig(kind="stub"))
    clean = "The impedance network transforms the load. Precision parts dominate the budget."
    out, report = revoice_document(clean, pack, stub, strength=0.0)
    assert report["summary"].get("rewritten", 0) == 0
    assert out.strip() == clean.strip()
