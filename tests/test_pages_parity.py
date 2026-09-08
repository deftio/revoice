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
