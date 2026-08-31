"""Pipeline branches: validation failure, lint retry, cohesion, rubrics, errors, style swaps."""

import re

import pytest

from revoice.core.pipeline import _validate, revoice_document
from revoice.core.voicepack import VoicePack
from tests.conftest import TRAIN, FakeProvider


def test_validate_branches():
    assert _validate("some text", "") == "empty"
    assert _validate("value is 42", "value is 43") == "numbers-changed"
    orig = "one two three four five six seven eight nine ten"
    assert _validate(orig, "much " * 30).startswith("length-ratio")
    assert _validate("we saw Alice in town yesterday", "we saw her in town yesterday").startswith("entities-lost")
    assert _validate("we saw Alice yesterday", "we saw Alice yesterday too") is None


def test_no_baselines(tmp_path, stub):
    pack = VoicePack.create(tmp_path / "d", "fresh")
    with pytest.raises(RuntimeError, match="no baselines"):
        revoice_document("hello there", pack, stub)


def test_bad_register(learned_pack, stub):
    with pytest.raises(RuntimeError, match="not in voice"):
        revoice_document("hello there", learned_pack, stub, register="nope")


def test_on_target_pass_and_short_pass(learned_pack, stub):
    reg = "professional"
    # >=25-word span identical to corpus -> attributed on-target, untouched
    msgs = []
    out, rep = revoice_document(TRAIN.format(i=0), learned_pack, stub, register=reg,
                                progress=lambda sid, m: msgs.append(m))
    e = rep["spans"][0]
    assert e["status"] == "unchanged" and "attribution_score" in e
    assert out == TRAIN.format(i=0)
    assert any("untouched" in m for m in msgs)


def test_strength_zero(learned_pack, stub):
    # short clean span at strength 0 -> pass
    out, rep = revoice_document("a short clean note.", learned_pack, stub, strength=0.0)
    assert rep["spans"][0]["status"] == "unchanged"
    # span with an AI tell is rewritten even at strength 0
    out2, rep2 = revoice_document("we delve into the notes.", learned_pack, stub, strength=0.0)
    assert rep2["spans"][0]["status"] == "rewritten"


def test_full_strength(learned_pack, stub):
    _, rep = revoice_document(TRAIN.format(i=0), learned_pack, stub, strength=1.0)
    assert rep["spans"][0]["status"] == "rewritten"


def test_validation_failure_keeps_original(learned_pack):
    fake = FakeProvider(lambda s, u, n: "the value is now 999 instead.")
    out, rep = revoice_document("the measured value is 42 here.", learned_pack, fake)
    e = rep["spans"][0]
    assert e["status"] == "validation-failed-kept-original"
    assert e["failure"] == "numbers-changed"
    assert "42" in out and "999" not in out


def test_lint_retry_success(learned_pack):
    def fn(system, user, n):
        if "banned patterns" in system:
            return "we examine circuits here today quickly."
        return "we delve into circuits here today quickly."

    fake = FakeProvider(fn)
    out, rep = revoice_document("we look at circuits here today, ok.", learned_pack, fake)
    e = rep["spans"][0]
    assert e["status"] == "rewritten" and e["output_tells"] == []
    assert "delve" not in out
    assert len(fake.calls) == 2


def test_lint_retry_still_dirty(learned_pack):
    fake = FakeProvider(lambda s, u, n: "we delve into circuits here today quickly.")
    _, rep = revoice_document("we look at circuits here today, ok.", learned_pack, fake)
    e = rep["spans"][0]
    assert e["status"] == "rewritten" and "delve" in e["output_tells"]


def test_provider_error(learned_pack):
    fake = FakeProvider(lambda s, u, n: (_ for _ in ()).throw(RuntimeError("boom")))
    msgs = []
    out, rep = revoice_document("rough note that needs a rewrite soon.", learned_pack, fake,
                                progress=lambda sid, m: msgs.append(m))
    e = rep["spans"][0]
    assert e["status"] == "error" and "boom" in e["error"]
    assert any("ERROR" in m for m in msgs)


def test_rubric_accept_and_reject(learned_pack, stub):
    # stub critic answers the first (best) choice -> accepted
    _, rep = revoice_document("gotta fix the amp maybe today ok.", learned_pack, stub, critic=stub)
    e = rep["spans"][0]
    assert e["status"] == "rewritten" and e["rubric"]["rejected_by"] == []

    # a critic that always answers the LAST (worst) choice -> rejected
    def worst(system, user, n):
        if "RUBRIC_JUDGE" in system:
            return re.findall(r"^- ([a-z_]+):", system, re.MULTILINE)[-1]
        return stub.complete(system, user)

    msgs = []
    _, rep2 = revoice_document("gotta fix the amp maybe today ok.", learned_pack, stub,
                               critic=FakeProvider(worst), progress=lambda sid, m: msgs.append(m))
    e2 = rep2["spans"][0]
    assert e2["status"].startswith("rubric-rejected")
    assert "voice_fidelity" in e2["rubric"]["rejected_by"]


def test_cohesion_edit_accepted(learned_pack):
    doc = "gotta test the alpha beta gamma module soon.\n\ngotta verify the theta iota kappa module soon."

    def fn(system, user, n):
        if "COHESION_EDIT" in system:
            return user.replace("soon", "shortly")
        return user.split("SPAN TO REWRITE:\n", 1)[-1].strip().replace("gotta", "need to")

    msgs = []
    out, rep = revoice_document(doc, learned_pack, FakeProvider(fn), cohesion=True,
                                progress=lambda sid, m: msgs.append(m))
    assert "cohesion-edited" in msgs
    edited = [e for e in rep["spans"] if e.get("cohesion_edited")]
    assert len(edited) == 1 and "shortly" in out
    assert rep["summary"]["cohesion-edited"] == 1


def test_cohesion_error_and_unchanged(learned_pack, stub):
    doc = "gotta test the alpha beta gamma module soon.\n\ngotta verify the theta iota kappa module soon."
    # stub returns span unchanged -> no cohesion edit
    _, rep = revoice_document(doc, learned_pack, stub, cohesion=True)
    assert rep["summary"]["cohesion-edited"] == 0

    def fn(system, user, n):
        if "COHESION_EDIT" in system:
            raise RuntimeError("cohesion down")
        return user.split("SPAN TO REWRITE:\n", 1)[-1].strip().replace("gotta", "need to")

    _, rep2 = revoice_document(doc, learned_pack, FakeProvider(fn), cohesion=True)
    assert rep2["summary"]["cohesion-edited"] == 0


def test_missing_profile_and_exemplars(learned_pack, stub):
    for f in learned_pack.profiles_dir.glob("*.json"):
        f.unlink()
    for f in learned_pack.exemplars_dir.glob("*.json"):
        f.unlink()
    _, rep = revoice_document("gotta clean this up maybe now ok.", learned_pack, stub)
    assert rep["spans"][0]["status"] == "rewritten"


def test_hard_swaps_and_style_section(learned_pack, stub):
    (learned_pack.params_dir / "style.yaml").write_text(
        "rules:\n  - Start with the point.\nswaps:\n  utilize: use\n")
    _, rep = revoice_document("gotta utilize the new amplifier maybe.", learned_pack, stub)
    e = rep["spans"][0]
    assert e["hard_swaps"] == ["utilize->use"]
    assert "use" in e["new"] and "utilize" not in e["new"]


def test_span_cautions_in_user_msg(learned_pack):
    seen = {}

    def fn(system, user, n):
        seen.setdefault("user", user)
        return user.split("SPAN TO REWRITE:\n", 1)[-1].strip()

    doc = ('gotta check https://example.com per Smith et al. (2020) [1] where she said '
           '"hold the line" at 3 dB and 10 kHz across the 5 mV offset window.')
    revoice_document(doc, learned_pack, FakeProvider(fn))
    assert "CAUTIONS:" in seen["user"] and "URLs present" in seen["user"]
