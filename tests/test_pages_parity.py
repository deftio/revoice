"""The browser port and the Python engine must agree.

`pages/voicespace.js` re-implements `revoice.voicemetric.space` so the compare page can
build a reference from text pasted into the browser, where there is no server to ask.
Two implementations of the same measurement drift silently: the page and the tool would
report different numbers for the same document, and nobody would notice until someone
compared them by hand.

These tests run the real JavaScript under node against the real Python on shared
fixtures. They skip (not fail) where node is unavailable, so the suite still runs in a
bare environment — but in CI, where node exists, a drift is a hard failure.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from revoice.voicemetric.space import AXIS_NAMES, coordinates

ROOT = Path(__file__).parent.parent
JS = ROOT / "pages" / "voicespace.js"

FIXTURES = {
    "narrative": ("When I was well grown, at last, I was sold and taken away, and I never saw "
                  "her again. She was broken-hearted, and so was I, and we cried; but she "
                  "comforted me as well as she could.\n\n"
                  "And she said we were sent into this world for a wise and good purpose, and "
                  "must do our duties without repining. You will find it so yourself, I think."),
    "institutional": ("The determination of the operational characteristics of the assembly "
                      "was undertaken with considerable caution; the classification of those "
                      "observations was subsequently completed.\n\n"
                      "Implementation of the recommendation is expected to be accomplished "
                      "following authorisation, and documentation will be provided."),
    "terse": "The valve failed. We replaced it. The test passed.\n\nNo further work is needed.",
}

node = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _js_coordinates(texts: dict[str, str]) -> dict[str, dict]:
    """Run the page's own JS and return its coordinates for each fixture."""
    script = f"""
const fs = require('fs');
const mod = new Function(fs.readFileSync({str(JS)!r}, 'utf8') +
  '; return {{vsCoordinates, VS_AXIS_NAMES, vsFitRegion, vsSimilarityReport, vsRenderChart}};')();
const texts = {json.dumps(texts)};
const out = {{}};
for (const k of Object.keys(texts)) out[k] = mod.vsCoordinates(texts[k]);
process.stdout.write(JSON.stringify({{coords: out, axes: mod.VS_AXIS_NAMES}}));
"""
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@node
def test_js_and_python_expose_the_same_axes():
    assert _js_coordinates({"x": "a b c."})["axes"] == list(AXIS_NAMES)


@node
def test_js_and_python_coordinates_agree():
    """Exact agreement, not approximate: the JS rounds where the fingerprint rounds.

    A loose tolerance here would hide precisely the drift this test exists to catch.
    """
    got = _js_coordinates(FIXTURES)["coords"]
    for name, text in FIXTURES.items():
        py = coordinates(text)
        for axis in AXIS_NAMES:
            assert got[name][axis] == pytest.approx(py[axis], abs=1e-9), \
                f"{name}/{axis}: js={got[name][axis]} python={py[axis]}"


@node
def test_js_similarity_report_has_the_python_shape():
    script = f"""
const fs = require('fs');
const m = new Function(fs.readFileSync({str(JS)!r}, 'utf8') +
  '; return {{vsFitRegion, vsSimilarityReport, vsRenderChart, VS_AXIS_NAMES}};')();
const pop = JSON.parse(fs.readFileSync({str(ROOT / 'pages' / 'demo' / 'population.json')!r}, 'utf8'));
const texts = {json.dumps(list(FIXTURES.values()))};
const region = m.vsFitRegion('ref', texts, pop);
const r = m.vsSimilarityReport(texts.join('\\n\\n'), region, pop);
process.stdout.write(JSON.stringify({{report: r, svg: m.vsRenderChart(r, 't', 's')}}));
"""
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    rep = out["report"]
    for key in ("overall", "low", "high", "confidence", "windows", "words",
                "interval_reliable", "axes", "voice"):
        assert key in rep, f"report is missing {key}"
    assert rep["low"] <= rep["overall"] <= rep["high"]
    assert set(rep["axes"]) == set(AXIS_NAMES)
    for d in rep["axes"].values():
        assert set(d) == {"similarity", "low", "high", "deviation"}
        assert 0.0 <= d["similarity"] <= 1.0
    assert out["svg"].startswith("<svg") and out["svg"].endswith("</svg>")
    assert "var(--vc-ink" in out["svg"], "chart must stay themeable"


@node
def test_js_similarity_is_deterministic():
    """Seeded PRNG, not Math.random: the same text must always give the same interval."""
    script = f"""
const fs = require('fs');
const m = new Function(fs.readFileSync({str(JS)!r}, 'utf8') +
  '; return {{vsFitRegion, vsSimilarityReport}};')();
const pop = JSON.parse(fs.readFileSync({str(ROOT / 'pages' / 'demo' / 'population.json')!r}, 'utf8'));
const t = {json.dumps(list(FIXTURES.values()))};
const region = m.vsFitRegion('r', t, pop);
const a = m.vsSimilarityReport(t.join('\\n\\n'), region, pop);
const b = m.vsSimilarityReport(t.join('\\n\\n'), region, pop);
process.stdout.write(JSON.stringify([a.low, a.high, b.low, b.high]));
"""
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    lo1, hi1, lo2, hi2 = json.loads(r.stdout)
    assert (lo1, hi1) == (lo2, hi2)


# ---------- the generated artefacts the pages depend on ----------


def test_population_json_matches_the_current_axis_set():
    """A stale population would silently mis-standardize every coordinate on the page."""
    pop = json.loads((ROOT / "pages" / "demo" / "population.json").read_text())
    assert pop["axes"] == list(AXIS_NAMES)
    assert set(pop["stats"]) == set(AXIS_NAMES)
    assert pop["n"] >= 20
    for mean_sd in pop["stats"].values():
        assert len(mean_sd) == 2 and mean_sd[1] > 0


def test_version_js_matches_the_installed_packages():
    """The nav prints this; it is generated, so it must not be allowed to go stale."""
    import revoice
    import revoice.voicemetric as voicemetric
    from revoice import rubric

    text = (ROOT / "pages" / "version.js").read_text()
    payload = json.loads(text[text.index("{"):text.rindex("}") + 1])
    assert payload["revoice"] == revoice.__version__
    assert payload["voicemetric"] == voicemetric.version()
    assert payload["voicemetric_signature"] == voicemetric.signature()
    assert payload["rubric"] == rubric.version()


def test_every_page_loads_the_version_script():
    for page in (ROOT / "pages").glob("*.html"):
        html = page.read_text()
        if 'src="site.js"' in html:
            assert 'src="version.js"' in html, f"{page.name} would show no version"
            assert html.index('version.js') < html.index('site.js'), \
                f"{page.name} loads version.js after site.js, so the nav sees nothing"


# ---------------------------------------------------------------------------------
# Grading a rewrite: transfer.py vs the same functions in the page.
#
# These are held to a tighter standard than the similarity report above. That report's
# interval is allowed to differ between page and tool because Python seeds it with
# random.Random, whose stream node cannot reproduce. A DELTA cannot afford that slack:
# `moved` is true only when the interval excludes zero, so a small divergence flips the
# verdict from "this rewrite worked" to "no measurable movement". transfer.py therefore
# implements the page's LCG rather than the other way round, and these tests assert the
# intervals match exactly, not approximately.

REWRITES = {
    # same content, restyled: short declaratives become a long subordinated sentence
    "restyled": (
        "The valve failed during the second test. We replaced it with a spare. "
        "The third test passed without incident.\n\n"
        "No further work is needed. The unit shipped on 14 March.",
        "Because the valve failed during the second test, we replaced it with a spare, "
        "after which the third test passed without incident.\n\n"
        "Nothing further is needed, and the unit shipped on 14 March."),
    # meaning damaged: a negation and a figure dropped
    "damaged": (
        "The sample did not exceed 40 percent saturation in any of the 12 runs.",
        "The sample exceeded saturation in the runs."),
    "identical": ("A paragraph.\n\nAnd another one entirely.",
                  "A paragraph.\n\nAnd another one entirely."),
}


_REGION_TEXTS = [FIXTURES["narrative"], FIXTURES["institutional"]]


def _population():
    from revoice.voicemetric.space import Population
    return Population.fit(list(FIXTURES.values()))


_POP = _population()


def _js_transfer(pairs: dict, population: dict, region_texts: list[str]) -> dict:
    """The population is fitted in Python and handed over, exactly as the page receives
    it from demo/population.json — so these tests isolate the transfer functions rather
    than re-testing coordinate parity, which the tests above already cover."""
    script = f"""
const fs = require('fs');
const mod = new Function(fs.readFileSync({str(JS)!r}, 'utf8') +
  '; return {{vsPreservation, vsStyleDelta, vsGrade, vsFitRegion}};')();
const pairs = {json.dumps(pairs)};
const pop = {json.dumps(population)};
const region = mod.vsFitRegion('ref', {json.dumps(region_texts)}, pop);
const out = {{}};
for (const k of Object.keys(pairs)) {{
  const [a, b] = pairs[k];
  out[k] = {{preservation: mod.vsPreservation(a, b),
             grade: mod.vsGrade(a, b, region, pop)}};
}}
process.stdout.write(JSON.stringify(out));
"""
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@node
def test_preservation_matches_the_page_exactly():
    """Meaning preservation is fully deterministic, so 'close' is not good enough."""
    from revoice.voicemetric.transfer import PRESERVATION_FAMILIES, preservation

    js = _js_transfer(REWRITES, _POP.to_dict(), _REGION_TEXTS)
    for name, (source, rewrite) in REWRITES.items():
        py = preservation(source, rewrite)
        got = js[name]["preservation"]
        for family in PRESERVATION_FAMILIES:
            assert py["families"][family] == pytest.approx(got["families"][family], abs=1e-9), (
                f"{name}/{family}: python {py['families'][family]} vs page {got['families'][family]}")
        assert py["weakest"] == got["weakest"], name
        assert py["overall"] == pytest.approx(got["overall"], abs=1e-9)


@node
def test_style_delta_and_its_interval_match_the_page():
    """The interval too — the verdict turns on whether it excludes zero."""
    from revoice.voicemetric.space import VoiceRegion
    from revoice.voicemetric.transfer import grade

    pop, region = _POP, VoiceRegion.fit("ref", _REGION_TEXTS, _POP)
    js = _js_transfer(REWRITES, pop.to_dict(), _REGION_TEXTS)

    for name, (source, rewrite) in REWRITES.items():
        py = grade(source, rewrite, region, pop)
        got = js[name]["grade"]
        for key in ("source", "rewrite", "delta", "low", "high"):
            assert py["style"][key] == pytest.approx(got["style"][key], abs=1e-9), (
                f"{name}/{key}: python {py['style'][key]} vs page {got['style'][key]}")
        assert py["style"]["moved"] == got["style"]["moved"], name
        assert py["style"]["regressed"] == got["style"]["regressed"], name
        assert py["style"]["interval_reliable"] == got["style"]["interval_reliable"], name
        assert py["verdict"] == got["verdict"], name


@node
def test_an_identical_rewrite_moves_nothing_in_both_implementations():
    """The control. If a text graded against itself reports movement, the measure is broken."""
    from revoice.voicemetric.space import VoiceRegion
    from revoice.voicemetric.transfer import grade

    region = VoiceRegion.fit("ref", _REGION_TEXTS, _POP)
    py = grade(FIXTURES["narrative"], FIXTURES["narrative"], region, _POP)
    assert py["style"]["delta"] == 0.0
    assert py["meaning"]["overall"] == 1.0
    assert not py["style"]["moved"] and not py["style"]["regressed"]

    js = _js_transfer({"self": [FIXTURES["narrative"], FIXTURES["narrative"]]},
                      _POP.to_dict(), _REGION_TEXTS)
    assert js["self"]["grade"]["style"]["delta"] == pytest.approx(0.0, abs=1e-9)
    assert js["self"]["grade"]["meaning"]["overall"] == 1.0
