"""Both engines report a version, and revoice records which one it used.

The point is reproducibility, not bookkeeping. `voicemetric`'s composite weights have
been refitted three times; each refit silently changed every score computed against an
existing baseline. A version alone would not have caught that — the API never moved —
so both engines also expose a SIGNATURE over the things that actually change numbers,
and revoice stamps it into the artefacts that outlive the code.
"""

import json
import re
from pathlib import Path

import pytest
import tomllib
import yaml

import revoice.voicemetric as voicemetric
from revoice import rubric
from revoice.core.metrics import engine_of, load_baselines, load_calibration
from revoice.core.rubrics import TEMPLATE

ROOT = Path(__file__).parent.parent


def _dims():
    return yaml.safe_load(TEMPLATE)["dimensions"]


# ---------- the shared contract ----------


@pytest.mark.parametrize("engine", [rubric, voicemetric])
def test_engine_exposes_a_version_string(engine):
    v = engine.version()
    assert isinstance(v, str)
    parts = v.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), f"{v} is not semver"
    assert v == engine.__version__


@pytest.mark.parametrize("engine", [rubric, voicemetric])
def test_engine_describe_is_json_serializable(engine):
    d = engine.describe()
    assert d["name"] and d["version"] == engine.version()
    json.dumps(d)          # it gets written into artefacts, so it must serialize


def test_version_is_exported_from_the_package_api():
    for engine in (rubric, voicemetric):
        assert "version" in engine.__all__ and "describe" in engine.__all__


# ---------- voicemetric: the signature tracks what changes scores ----------


def test_voicemetric_signature_is_stable_across_calls():
    assert voicemetric.signature() == voicemetric.signature()


def test_voicemetric_signature_moves_when_the_weights_are_refitted(monkeypatch):
    """The failure this exists to catch: a refit changes every score, API untouched."""
    before = voicemetric.signature()
    weights = {**voicemetric.WEIGHTS, "delta": voicemetric.WEIGHTS["delta"] + 0.05}
    monkeypatch.setattr("revoice.voicemetric.WEIGHTS", weights)
    assert voicemetric.signature() != before


def test_voicemetric_signature_moves_when_the_axes_change(monkeypatch):
    before = voicemetric.signature()
    monkeypatch.setattr("revoice.voicemetric.AXIS_NAMES",
                        (*voicemetric.AXIS_NAMES, "an_invented_axis"))
    assert voicemetric.signature() != before


def test_voicemetric_describe_carries_the_scoring_configuration():
    d = voicemetric.describe()
    assert d["signature"] == voicemetric.signature()
    assert set(d["weights"]) == set(d["components"])
    assert d["llm"] is False


# ---------- rubric: the signature tracks the spec, which the caller owns ----------


def test_rubric_signature_depends_on_the_spec_not_just_the_engine():
    dims = _dims()
    heavier = {**dims, "voice_fidelity": {**dims["voice_fidelity"], "weight": 0.9}}
    assert rubric.rubric_signature(heavier) != rubric.rubric_signature(dims)


def test_rubric_signature_ignores_cosmetic_edits():
    """Rewording a description must not invalidate comparability; changing a score must."""
    dims = _dims()
    reworded = {**dims, "verbosity": {**dims["verbosity"], "description": "totally rewritten"}}
    assert rubric.rubric_signature(reworded) == rubric.rubric_signature(dims)
    rescored = {**dims, "verbosity": {**dims["verbosity"],
                                      "scores": {**dims["verbosity"]["scores"], "matched": 0.5}}}
    assert rubric.rubric_signature(rescored) != rubric.rubric_signature(dims)


def test_rubric_signature_is_order_independent():
    dims = _dims()
    assert rubric.rubric_signature(dict(reversed(list(dims.items())))) == \
        rubric.rubric_signature(dims)


def test_judge_all_stamps_the_engine_into_its_result(stub):
    from revoice.rubric import judge_all

    r = judge_all(stub.complete, _dims(), candidate="Some rewritten text.", original="Some text.")
    assert r["engine"]["name"] == "rubric"
    assert r["engine"]["version"] == rubric.version()
    assert r["engine"]["rubric_signature"] == rubric.rubric_signature(_dims())


# ---------- revoice records what it used ----------


def test_learn_stamps_the_engine_into_the_pack(learned_pack):
    stamped = engine_of(learned_pack)
    assert stamped["name"] == "voicemetric"
    assert stamped["version"] == voicemetric.version()
    assert stamped["signature"] == voicemetric.signature()
    assert stamped["built"]
    assert learned_pack.manifest()["voicemetric"]["signature"] == voicemetric.signature()


def test_the_stamp_never_leaks_into_the_registers(learned_pack):
    """`_engine` shares the top level with register keys, so readers must strip it."""
    raw = json.loads((learned_pack.params_dir / "baselines.json").read_text())
    assert "_engine" in raw
    assert "_engine" not in load_baselines(learned_pack)
    assert "_engine" not in load_calibration(learned_pack)
    assert all(not k.startswith("_") for k in load_baselines(learned_pack))


def test_engine_of_an_unbuilt_pack_is_empty(tmp_path):
    from revoice.core.voicepack import VoicePack

    assert engine_of(VoicePack.create(tmp_path / "d", "fresh")) == {}


def test_status_warns_when_a_pack_was_built_by_another_engine_build(learned_cwd, monkeypatch):
    """The whole point of the stamp: a stale pack must announce itself.

    Its stored calibration bands were measured under a different scoring configuration,
    so anything computed against them today is quietly incomparable.
    """
    from typer.testing import CliRunner

    from revoice.cli import app

    baselines = learned_cwd / "data" / "t" / "params" / "baselines.json"
    data = json.loads(baselines.read_text())
    data["_engine"] = {**data["_engine"], "version": "0.0.1", "signature": "0000deadbeef"}
    baselines.write_text(json.dumps(data))

    r = CliRunner().invoke(app, ["status", "t"])
    assert r.exit_code == 0, r.output
    assert "not comparable across signatures" in r.output
    assert "0000deadbeef" in r.output and voicemetric.signature() in r.output


def test_status_is_quiet_when_the_pack_matches_this_build(learned_cwd):
    from typer.testing import CliRunner

    from revoice.cli import app

    r = CliRunner().invoke(app, ["status", "t"])
    assert r.exit_code == 0, r.output
    assert "not comparable" not in r.output


def test_doctor_reports_both_engines(learned_cwd):
    from typer.testing import CliRunner

    from revoice.cli import app

    r = CliRunner().invoke(app, ["doctor"])
    assert "voicemetric" in r.output and voicemetric.signature() in r.output
    assert f"rubric      {rubric.version()}" in r.output


# ---------- one version, one place ----------


def test_the_version_is_declared_exactly_once_in_the_codebase():
    """A version written twice is a version that will eventually be wrong in one of
    them, silently: the package says one thing, the site says another, and a bug report
    cites a build that never existed."""
    import revoice

    literal = re.escape(revoice.__version__)
    hits = []
    for path in list(ROOT.glob("*.toml")) + list((ROOT / "revoice").rglob("*.py")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(rf'^\s*(?:__version__|version)\s*=\s*["\']{literal}["\']', line):
                hits.append(f"{path.relative_to(ROOT)}:{i}")
    assert len(hits) == 1 and hits[0].startswith("revoice/__init__.py"), (
        "revoice's version literal must appear in exactly one place "
        f"(revoice/__init__.py); found: {hits}")


def test_pyproject_derives_its_version_rather_than_repeating_it():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "version" not in data["project"], \
        "pyproject declares a literal version; it should be dynamic"
    assert "version" in data["project"].get("dynamic", []), \
        "pyproject should list 'version' as dynamic"
    assert data["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "revoice.__version__"}


def test_the_installed_package_metadata_matches_the_runtime():
    """The dynamic-version wiring is only correct if the built metadata agrees."""
    from importlib.metadata import version as dist_version

    import revoice

    assert dist_version("revoice") == revoice.__version__


def test_revoice_exposes_version_like_the_engines_do():
    import revoice

    assert revoice.version() == revoice.__version__
    assert {revoice.version(), rubric.version(), voicemetric.version()}, "all three callable"
