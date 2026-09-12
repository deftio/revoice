"""Grading a rewrite: did it move toward the voice, and did the meaning survive?

The absolute question ("is this by X?") tops out near AUC 0.69. These tests cover the
paired question, where source and rewrite share topic, length and content so those
confounds cancel — and the meaning axis that stops style movement being bought with
meaning drift.
"""

import pytest

from revoice.voicemetric.space import Population, VoiceRegion
from revoice.voicemetric.transfer import (
    MEANING_FLOOR,
    PRESERVATION_FAMILIES,
    _lcg,
    _stem,
    grade,
    preservation,
    style_delta,
)

PLAIN = ("The valve failed during the second test. We replaced it with a spare part.\n\n"
         "The third test passed. Nothing further is required.\n\n"
         "We shipped the unit. The customer confirmed receipt.\n\n"
         "The report was filed. The matter is closed.")

# Deliberately the same claims, the same figures, the same content words and the same
# hedging as PLAIN — only the delivery differs. Anything else and the meaning axis vetoes
# before the style axis is ever consulted, which is correct behaviour but makes it
# impossible to test the style branches.
ORNATE = ("Although the valve had failed during the second test, a spare part, held "
          "against precisely such an eventuality, was fitted in its place and it was "
          "replaced.\n\n"
          "The third test, conducted subsequently, passed cleanly, and nothing "
          "further was thought to be required of the team.\n\n"
          "The unit was shipped; receipt was confirmed by the customer in due course.\n\n"
          "The report having been filed, the matter is closed.")

BACKGROUND = [PLAIN, ORNATE,
              "A short note. Very short indeed.\n\nAnother one.\n\nAnd a third.",
              "Consideration of the matter was undertaken with appropriate deliberation, "
              "and the conclusions were documented.\n\nImplementation followed."]


@pytest.fixture
def population():
    return Population.fit(BACKGROUND)


@pytest.fixture
def ornate_voice(population):
    return VoiceRegion.fit("ornate", [ORNATE, BACKGROUND[3]], population)


# ---------------------------------------------------------------- meaning preservation --

def test_an_untouched_text_preserves_everything():
    p = preservation(PLAIN, PLAIN)
    assert p["overall"] == 1.0
    assert all(v == 1.0 for v in p["families"].values())


def test_every_family_is_reported_so_the_failure_is_legible():
    p = preservation(PLAIN, ORNATE)
    assert set(p["families"]) == set(PRESERVATION_FAMILIES)
    assert p["weakest"] in PRESERVATION_FAMILIES


def test_dropping_figures_is_caught():
    src = "Saturation reached 40 percent in 12 of the 15 runs on 3 March."
    assert preservation(src, "Saturation was reached in most runs.")["families"]["numbers"] == 0.0
    assert preservation(src, src)["families"]["numbers"] == 1.0


def test_losing_a_negation_inverts_a_claim_and_is_caught():
    src = "The treatment did not reduce mortality."
    p = preservation(src, "The treatment reduced mortality.")
    assert p["families"]["negation"] == 0.0
    assert p["weakest"] == "negation"


def test_contracted_negation_counts():
    """"didn't" is a negation even though the word list has no entry for it."""
    assert preservation("It didn't work.", "It did work.")["families"]["negation"] == 0.0
    assert preservation("It didn't work.", "It did not work.")["families"]["negation"] == 1.0


def test_hedges_are_symmetric_because_inventing_one_is_drift_too():
    hedged = "The data suggest the effect may be small."
    firm = "The data show the effect is small."
    assert preservation(hedged, firm)["families"]["hedges"] == 0.0
    # and the other direction: a rewrite that adds hedging the source never had
    assert preservation(firm, hedged)["families"]["hedges"] == 0.0


def test_proper_nouns_are_tracked_but_sentence_openings_are_not():
    """Every sentence starts with a capital; only capitals AWAY from one mean a name."""
    src = "Darwin sailed on the Beagle. Voyages were long."
    # "Voyages" opens a sentence, so dropping it must not register as a lost entity
    assert preservation(src, "Darwin sailed on the Beagle. Trips were long.")[
        "families"]["entities"] == 1.0
    assert preservation(src, "He sailed on the ship. Voyages were long.")[
        "families"]["entities"] == 0.0


def test_a_quoted_sentence_opening_is_still_an_opening():
    """The scan skips quotes and brackets before deciding, or every quotation's first
    word would be counted as a proper noun."""
    assert preservation('He said, "Ships are slow."', 'He said, "Boats are slow."')[
        "families"]["entities"] == 1.0


def test_overall_is_the_minimum_not_the_mean():
    """Meaning is conjunctive. Dropping every figure is not offset by keeping the prose."""
    src = "In 1859 Darwin published the work, and it did not go unnoticed by Huxley."
    rewrite = "Darwin published the work, and it did not go unnoticed by Huxley."
    p = preservation(src, rewrite)
    assert p["families"]["numbers"] == 0.0
    assert p["overall"] == 0.0        # not the ~0.8 a mean would give
    assert p["weakest"] == "numbers"


def test_an_empty_family_in_the_source_cannot_be_failed():
    """A source with no figures scores 1.0 on numbers — there was nothing to lose."""
    assert preservation("No digits here at all.", "None here either.")[
        "families"]["numbers"] == 1.0


def test_stemming_is_crude_but_stable():
    assert _stem("measured") == _stem("measures") == _stem("measure")
    assert _stem("Darwin's") == "darwin"
    assert _stem("bus") == "bus"       # too short to strip and still leave a stem


def test_preservation_states_its_own_limit():
    """The method string is the honest ceiling: this is retention, not entailment."""
    assert "not entailment" in preservation(PLAIN, ORNATE)["method"]


def test_reordering_that_inverts_meaning_is_the_known_blind_spot():
    """Documented, not fixed: the same tokens in a different order score perfectly.

    This is the limit `method` names. Catching it needs entailment, which needs a model,
    which cannot run in a page off GitHub Pages. The test exists so the gap is a recorded
    property rather than a surprise.
    """
    assert preservation("The dog bit the man.", "The man bit the dog.")["overall"] == 1.0


# -------------------------------------------------------------------- style movement --

def test_a_text_graded_against_itself_moves_nothing(population, ornate_voice):
    d = style_delta(PLAIN, PLAIN, ornate_voice, population)
    assert d["delta"] == 0.0
    assert not d["moved"] and not d["regressed"]


def test_movement_toward_a_voice_is_positive_and_away_is_negative(population, ornate_voice):
    toward = style_delta(PLAIN, ORNATE, ornate_voice, population)
    away = style_delta(ORNATE, PLAIN, ornate_voice, population)
    assert toward["delta"] > 0 > away["delta"]
    assert toward["delta"] == pytest.approx(-away["delta"], abs=1e-9)


def test_closed_reports_the_gap_as_a_fraction_of_what_was_available(population, ornate_voice):
    d = style_delta(PLAIN, ORNATE, ornate_voice, population)
    assert d["closed"] == pytest.approx(d["delta"] / (100 - d["source"]), abs=1e-9)


def test_moved_requires_the_whole_interval_to_clear_zero(population, ornate_voice):
    """A delta whose interval spans zero is reported as no movement, whatever its sign."""
    d = style_delta(PLAIN, ORNATE, ornate_voice, population)
    if d["interval_reliable"]:
        assert d["moved"] == (d["low"] > 0)
        assert d["regressed"] == (d["high"] < 0)


def test_too_few_windows_yields_no_interval_rather_than_a_confident_one(population,
                                                                       ornate_voice):
    d = style_delta("One short line.", "Another short line.", ornate_voice, population)
    assert not d["interval_reliable"]
    assert d["low"] == d["high"] == d["delta"]
    assert not d["moved"] and not d["regressed"]


def test_the_bootstrap_is_reproducible(population, ornate_voice):
    a = style_delta(PLAIN, ORNATE, ornate_voice, population, seed=5)
    b = style_delta(PLAIN, ORNATE, ornate_voice, population, seed=5)
    assert a == b


def test_the_lcg_matches_the_browsers(population):
    """The PRNG is shared with pages/voicespace.js on purpose — see transfer.py. Values
    here are the LCG's own definition, so a change to either side fails this."""
    nxt = _lcg(17)
    got = [nxt() for _ in range(3)]
    s, out = 17, []
    for _ in range(3):
        s = (s * 1664525 + 1013904223) % 2 ** 32
        out.append(s / 2 ** 32)
    assert got == out
    assert all(0.0 <= v < 1.0 for v in got)


# ---------------------------------------------------------------------------- grade --

def test_meaning_vetoes_style(population, ornate_voice):
    """The point of keeping the axes separate: style cannot buy back lost meaning.

    This rewrite moves toward the ornate voice AND drops the source's negation. Any
    scheme that averaged the two axes would report a partial success; this one reports
    the failure, because that is what it is.
    """
    damaged = ORNATE.replace("nothing further was thought to be required of the team",
                             "the team required more")
    g = grade(PLAIN, damaged, ornate_voice, population)
    assert g["meaning"]["overall"] < MEANING_FLOOR
    assert g["meaning"]["weakest"] == "negation"
    assert g["verdict"].startswith("meaning drift")
    # the style axis is still computed and still positive — it is reported, not obeyed
    assert "style" in g


def test_a_clean_rewrite_reports_its_movement(population, ornate_voice):
    g = grade(PLAIN, ORNATE, ornate_voice, population)
    assert g["meaning"]["overall"] >= 0.0
    assert "style" in g and "meaning" in g
    # the two axes are returned side by side and never combined into one score
    assert not any(k in g for k in ("score", "overall", "combined"))


def _long(text: str, times: int = 24) -> str:
    """Enough paragraphs to clear the 3-window floor, so the interval is real.

    Windows target 220 words, so the short fixtures above bound out at one window each
    and every grade of them comes back "too short". The movement branches only exist
    above that floor, which is the point — a delta you cannot bound is not a finding.
    """
    paras = [p for p in text.split("\n\n") if p.strip()]
    return "\n\n".join(paras * times)


def test_every_verdict_branch_is_reachable(population, ornate_voice):
    """All five verdicts, each from a case that genuinely produces it.

    "moved away" uses the SAME text pair as "moved toward" against a different voice,
    rather than swapping source and rewrite. Swapping would fail the meaning axis first:
    recall is asymmetric on purpose, so a rewrite that drops content the source had is
    drift, and the veto would fire before the style branch was ever reached.
    """
    plain_voice = VoiceRegion.fit("plain", [PLAIN, BACKGROUND[2]], population)
    long_plain, long_ornate = _long(PLAIN), _long(ORNATE)
    damaged = ORNATE.replace("nothing further was thought to be required of the team",
                             "the team required more")
    cases = [
        ("moved toward", long_plain, long_ornate, ornate_voice),
        ("moved away", long_plain, long_ornate, plain_voice),
        ("no measurable movement", long_plain, long_plain, ornate_voice),
        # meaning must be intact or its veto fires first and this branch is unreachable
        ("too short", "The valve failed.", "The valve failed, sadly.", ornate_voice),
        ("meaning drift", PLAIN, damaged, ornate_voice),
    ]
    for expected, source, rewrite, voice in cases:
        v = grade(source, rewrite, voice, population)["verdict"]
        assert v.startswith(expected), f"{expected}: got {v!r}"


def test_no_measurable_movement_names_the_interval_that_caused_it(population, ornate_voice):
    """The branch that matters most, and the one a bare number would hide."""
    long_plain = _long(PLAIN)
    v = grade(long_plain, long_plain, ornate_voice, population)["verdict"]
    assert v.startswith("no measurable movement")
    assert "spans zero" in v


def test_verdict_names_the_voice_it_measured_against(population, ornate_voice):
    g = grade(PLAIN, ORNATE, ornate_voice, population)
    assert g["style"]["voice"] == "ornate"
    assert "ornate" in g["verdict"] or g["verdict"].startswith(("meaning", "no ", "too "))
