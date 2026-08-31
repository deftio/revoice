from revoice.core import lint
from revoice.core.style import apply_hard_swaps, render_prompt_section

STYLE = {
    "rules": ["Prefer plain words."],
    "phrases": {"In any event,": ["Moving on,"]},
    "lexicon": {"vehicle": {"automobile": 0.9, "car": 0.09, "4 wheeler": 0.01}},
    "swaps": {"utilize": "use"},
}


def test_hard_swaps_case_preserving():
    out, applied = apply_hard_swaps("We utilize this. Utilize caution.", STYLE)
    assert out == "We use this. Use caution."
    assert applied == ["utilize->use"]


def test_lexicon_rendered_qualitatively_no_numbers():
    section = render_prompt_section(STYLE)
    assert "automobile" in section and "0.9" not in section
    assert "prefers" in section


def test_ai_tell_lint():
    patterns = lint.load_patterns(None)
    hits = lint.scan(
        "In today's fast-paced world, it's important to note that we leverage synergy.", patterns
    )
    assert "in-todays-world" in hits and "leverage" in hits
    assert lint.scan("The resistor gets hot.", patterns) == []
    assert lint.score("delve delve delve", patterns) > 50
