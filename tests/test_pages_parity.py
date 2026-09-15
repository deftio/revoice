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
import sys
from pathlib import Path

import pytest

from revoice.voicemetric.space import AXIS_NAMES, coordinates

ROOT = Path(__file__).parent.parent
JS = ROOT / "pages" / "voicespace.js"
ENGINE = ROOT / "pages" / "voicemetric.js"
CONSTANTS = ROOT / "pages" / "engine-constants.js"

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
const mod = new Function(fs.readFileSync({str(CONSTANTS)!r}, 'utf8') +
  fs.readFileSync({str(ENGINE)!r}, 'utf8') + fs.readFileSync({str(JS)!r}, 'utf8') +
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
const m = new Function(fs.readFileSync({str(CONSTANTS)!r}, 'utf8') +
  fs.readFileSync({str(ENGINE)!r}, 'utf8') + fs.readFileSync({str(JS)!r}, 'utf8') +
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
const m = new Function(fs.readFileSync({str(CONSTANTS)!r}, 'utf8') +
  fs.readFileSync({str(ENGINE)!r}, 'utf8') + fs.readFileSync({str(JS)!r}, 'utf8') +
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
const mod = new Function(fs.readFileSync({str(CONSTANTS)!r}, 'utf8') +
  fs.readFileSync({str(ENGINE)!r}, 'utf8') + fs.readFileSync({str(JS)!r}, 'utf8') +
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


# =================================================================================
# The engine itself: pages/voicemetric.js against features.py + baseline.py.
#
# This is the half that had never been tested, and the cost of that shows in the
# history. pages/stylometry.js began life as "a JS port of the demo subset", the Python
# was refitted three times and grew six components, and nothing compared them. By the
# time anyone measured, the page was scoring with `ngram` weighted 0.600 against a
# fitted 0.181 and no `richness` or `structure` at all — AUC 0.688 against Python's
# 0.793 on the same 112 trials, and it ranked Twain's own other work as less like Twain
# than Bret Harte was.
#
# Tolerances are per family and stated, not bit-exact. The residual is rounding —
# Python's round() breaks exact ties to even, JavaScript's Math.round() away from zero,
# and fingerprint() rounds ~25 values. A ratio like 1/32 is an exact tie at four places.
# What the tolerances do NOT permit is a difference in what is computed: a missing
# component or a wrong weight moves a composite by whole points, not by 1e-2.

FP_TOLERANCE = 0.011        # one unit at the coarsest rounding in fingerprint() (2 dp)
COMPONENT_TOLERANCE = 1e-9  # components are computed from rounded inputs, then rounded
COMPOSITE_TOLERANCE = 0.05  # out of 100


def _engine_script(body: str) -> str:
    return f"""
const fs = require('fs');
eval(fs.readFileSync({str(CONSTANTS)!r}, 'utf8'));
eval(fs.readFileSync({str(ENGINE)!r}, 'utf8'));
eval(fs.readFileSync({str(JS)!r}, 'utf8'));
{body}
"""


def _run_node(body: str):
    r = subprocess.run(["node", "-e", _engine_script(body)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _flatten(prefix, value, out):
    """Every number in a fingerprint, addressed by path, so a diff names its own field."""
    if isinstance(value, bool):
        out[prefix] = float(value)
    elif isinstance(value, (int, float)):
        out[prefix] = float(value)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}", v, out)
    return out


@node
def test_fingerprint_matches_the_page_field_for_field():
    """All 29 fields, on real corpus prose rather than a toy string."""
    from revoice.voicemetric.features import fingerprint

    texts = dict(FIXTURES)
    corpus = ROOT / "bench-corpus" / "twain" / "training-data"
    if corpus.is_dir():
        for f in sorted(corpus.glob("*.md"))[:2]:
            texts[f.stem] = f.read_text()[:6000]

    js = _run_node(f"""
const texts = {json.dumps(texts)};
const out = {{}};
for (const k of Object.keys(texts)) out[k] = vmFingerprint(texts[k]);
process.stdout.write(JSON.stringify(out));""")

    for name, text in texts.items():
        py, got = fingerprint(text), js[name]
        assert set(py) == set(got), f"{name}: field sets differ"
        a, b = _flatten("", py, {}), _flatten("", got, {})
        assert set(a) == set(b), f"{name}: leaf sets differ"
        for key in a:
            assert abs(a[key] - b[key]) <= FP_TOLERANCE, (
                f"{name}{key}: python {a[key]!r} vs page {b[key]!r}")


@node
def test_the_composite_and_every_component_match_the_page():
    """The number the page actually shows, against the number `revoice stats` shows."""
    from revoice.voicemetric.baseline import COMPONENTS, baseline_from_texts, score_text
    from revoice.voicemetric.space import windows

    corpus = ROOT / "bench-corpus"
    if not corpus.is_dir():
        pytest.skip("bench corpus not fetched")
    ref = sorted((corpus / "twain" / "training-data").glob("*.md"))[0].read_text()[:14000]
    cands = {}
    for author in ("twain", "darwin", "harte"):
        d = corpus / author / "training-data"
        if d.is_dir():
            cands[author] = sorted(d.glob("*.md"))[-1].read_text()[:4000]

    ref_windows = windows(ref)
    js = _run_node(f"""
const refw = {json.dumps(ref_windows)}, cands = {json.dumps(cands)};
const base = vmBaselineFromTexts(refw);
const out = {{}};
for (const k of Object.keys(cands)) out[k] = vmScoreText(cands[k], base);
process.stdout.write(JSON.stringify(out));""")

    base = baseline_from_texts(ref_windows)
    for name, text in cands.items():
        py, got = score_text(text, base), js[name]
        assert abs(py["composite"] - got["composite"]) <= COMPOSITE_TOLERANCE, (
            f"{name}: composite python {py['composite']} vs page {got['composite']}")
        for c in COMPONENTS:
            assert abs(py["components"][c] - got["components"][c]) <= COMPONENT_TOLERANCE, (
                f"{name}/{c}: python {py['components'][c]} vs page {got['components'][c]}")
        assert abs(py["burrows_delta"] - got["burrows_delta"]) <= 1e-3
        assert py["reliable"] == got["reliable"]


@node
def test_the_page_uses_the_fitted_weights_not_a_copy_of_them():
    """The specific failure that motivated all of this.

    The old engine had 0.2/0.6/0.1/0.1 hand-typed into it while the fitted values were
    0.318/0.181/0.0/0.332 across ten components. Nothing detected it for months because
    nothing compared them. Now the weights are generated, and this asserts the generated
    file still agrees with the Python it was generated from.
    """
    from revoice.voicemetric.baseline import COMPONENTS, WEIGHTS

    js = _run_node("process.stdout.write(JSON.stringify("
                   "{weights: VM_CONST.WEIGHTS, components: VM_CONST.COMPONENTS}));")
    assert js["components"] == list(COMPONENTS)
    assert js["weights"] == pytest.approx(WEIGHTS)


@node
def test_generated_constants_match_python_exactly():
    """Every shared constant, not only the weights. Sets are compared as sets."""
    from revoice.voicemetric.baseline import PUNCTS, SCALARS
    from revoice.voicemetric.features import (
        FUNCTION_WORDS,
        OPENER_CLASSES,
        PARA_HIST_BINS,
        SENT_HIST_BINS,
        STOP,
        WORD_HIST_BINS,
    )
    from revoice.voicemetric.space import AXIS_NAMES, MIN_SPREAD
    from revoice.voicemetric.transfer import HEDGES, MEANING_FLOOR, NEGATIONS

    js = _run_node("process.stdout.write(JSON.stringify(VM_CONST));")
    assert js["FUNCTION_WORDS"] == list(FUNCTION_WORDS)
    assert js["OPENER_CLASSES"] == list(OPENER_CLASSES)
    assert js["SENT_HIST_BINS"] == list(SENT_HIST_BINS)
    assert js["WORD_HIST_BINS"] == list(WORD_HIST_BINS)
    assert js["PARA_HIST_BINS"] == list(PARA_HIST_BINS)
    assert js["PUNCTS"] == list(PUNCTS)
    assert js["SCALARS"] == list(SCALARS)
    assert set(js["STOP"]) == STOP
    assert set(js["NEGATIONS"]) == NEGATIONS
    assert set(js["HEDGES"]) == HEDGES
    assert js["MEANING_FLOOR"] == MEANING_FLOOR
    assert js["MIN_SPREAD"] == MIN_SPREAD
    assert [a["name"] for a in js["AXES"]] == list(AXIS_NAMES)


@node
def test_the_generated_constants_file_is_not_stale():
    """Regenerating must be a no-op. Otherwise the page ships constants nobody fitted."""
    import subprocess as sp

    before = CONSTANTS.read_bytes()
    try:
        sp.run([sys.executable, str(ROOT / "scripts" / "export_demo_baselines.py")],
               capture_output=True, check=True, cwd=ROOT)
        assert CONSTANTS.read_bytes() == before, (
            "pages/engine-constants.js is stale — run scripts/export_demo_baselines.py")
    finally:
        CONSTANTS.write_bytes(before)


def test_every_ported_function_has_a_python_counterpart_under_test():
    """The guard that would have caught the original drift.

    A function added to the JS engine without a Python twin, or a Python function
    ported without a parity test, is how the two implementations come apart. This
    enumerates what the JS exports and requires each one to be either paired with a
    Python function or explicitly declared page-only.
    """
    import re

    src = ENGINE.read_text()
    # everything above the PAGE-ONLY marker is a port and must be paired
    ported_src = src.split("PAGE-ONLY, NO PYTHON COUNTERPART")[0]
    exported = set(re.findall(r"^function (vm[A-Za-z0-9_]+)", ported_src, re.M))

    # vmX -> the Python name it mirrors; helpers that exist only to make JS behave like
    # Python (rounding, Counter, stable sort) are listed as such
    PAIRS = {
        "vmRound": None, "vmSet": None, "vmCount": None, "vmSumValues": None,
        "vmMostCommon": None, "vmAccumulate": None, "vmWordsIn": None,
        "vmSyllables": "_syllables", "vmTokenize": "tokenize", "vmHist": "_hist",
        "vmYulesK": "yules_k", "vmMtld": "mtld", "vmOpenerClass": "_opener_class",
        "vmCharNgramProfile": "char_ngram_profile",
        "vmWordBigramProfile": "word_bigram_profile",
        "vmFunctionWordBigramProfile": "function_word_bigram_profile",
        "vmContentTerms": "content_terms", "vmTfidfVector": "tfidf_vector",
        "vmCosine": "cosine", "vmFingerprint": "fingerprint",
        "vmMeanStd": "_mean_std", "vmBaselineFromTexts": "baseline_from_texts",
        # runtime version support, mirroring the package accessors
        "vmVersion": "version", "vmVersionInfo": "version_info",
        "vmSignature": "signature", "vmVersions": "versions",
        "vmScalarSimilarity": "_scalar_similarity",
        "vmHistSimilarity": "_hist_similarity", "vmScoreText": "score_text",
    }
    missing = exported - set(PAIRS)
    assert not missing, (
        f"ported JS functions with no declared Python counterpart: {sorted(missing)}. "
        "Add the pair here (and a parity assertion), or move the function below the "
        "PAGE-ONLY marker in pages/voicemetric.js.")

    import revoice
    from revoice import voicemetric as py_vm
    from revoice.voicemetric import baseline as py_baseline
    from revoice.voicemetric import features as py_features

    sources = (py_features, py_baseline, py_vm, revoice)
    for js_name, py_name in PAIRS.items():
        if py_name is None:
            continue
        assert any(hasattr(src, py_name) for src in sources), (
            f"{js_name} claims to mirror {py_name}, which no longer exists in Python")


def test_the_stale_engine_is_gone():
    """pages/stylometry.js was a third implementation of the composite. It is deleted,
    and this keeps it deleted — reintroducing it would reintroduce the drift."""
    assert not (ROOT / "pages" / "stylometry.js").exists()
    # Check for LOADING it, not for mentioning it: the pages carry a comment explaining
    # what the old engine was and why it went, and that history is worth keeping. (The
    # blunt version of this assertion failed on its own explanation.)
    for page in (ROOT / "pages").glob("*.html"):
        assert 'src="stylometry.js"' not in page.read_text(), f"{page.name} still loads it"


# ---------------------------------------------------------------------------------
# The Markdown export.
#
# report.html has a "download Markdown" button; `revoice space --report out.md` writes
# the same document. Two generators of one artefact is exactly the shape that produced
# the stylometry.js drift, so it gets the same treatment: identical output, asserted.
#
# The reports themselves are computed ONCE in Python and handed to both sides, so this
# isolates the formatting. Bootstrap intervals are allowed to differ between the two
# implementations (Python seeds with random.Random, which node cannot reproduce), and
# leaving that in would make this test about the PRNG rather than about the document.

MD_SAMPLES = {
    "Twain — held out": "narrative",
    "Institutional prose": "institutional",
}


def _long(text: str, times: int = 26) -> str:
    """Enough paragraphs to clear the three-window floor.

    Below it a document gets no interval at all, `worst_overlap` returns None, and the
    Markdown skips the overlap section entirely — so a short fixture would leave the most
    important half of this document untested while the test still passed.
    """
    paras = [p for p in text.split("\n\n") if p.strip()]
    return "\n\n".join(paras * times)


def _reports_for_markdown():
    from revoice.voicemetric.space import Population, VoiceRegion, similarity_report

    pop = Population.fit(list(FIXTURES.values()))
    region = VoiceRegion.fit("your reference",
                             [FIXTURES["narrative"], FIXTURES["institutional"]], pop)
    out = []
    for name, key in MD_SAMPLES.items():
        r = similarity_report(_long(FIXTURES[key]), region, pop)
        assert r["interval_reliable"], f"{name} still has no interval"
        out.append((name, f"/tmp/{name}.md", r))
    return out


@node
def test_the_markdown_export_matches_the_cli_byte_for_byte():
    from revoice.voicemetric import chart

    items = _reports_for_markdown()
    payload = [{"name": n, "report": r} for n, _s, r in items]
    js = _run_node(f"""
const items = {json.dumps(payload)};
process.stdout.write(JSON.stringify(
  {{md: vsMarkdownReport(items, 'your reference', 'voicemetric 9.9.9 (deadbeef)')}}));""")

    py = chart.markdown(items, voice="your reference",
                        engine="voicemetric 9.9.9 (deadbeef)")
    assert js["md"] == py, (
        "the page's Markdown export and `revoice space --report out.md` have diverged\n"
        f"--- page ---\n{js['md'][:900]}\n--- cli ---\n{py[:900]}")


@node
def test_the_markdown_leads_with_the_overlap_not_the_ranking():
    """The point of the document. A ranked table invites the order to be read as a
    result; on this measure it usually is not one, so the overlap is stated in words
    before any number is ranked."""
    from revoice.voicemetric import chart

    items = _reports_for_markdown()
    md = chart.markdown(items, voice="v")
    assert md.index("## What this says") < md.index("## Every reading on one scale")
    assert "not evidence" in md or "do not overlap" in md
    # every score carries its interval, in the table and in the per-sample sections
    for _n, _s, r in items:
        if r["interval_reliable"]:
            assert f"{r['low']:.0f}–{r['high']:.0f}" in md


def test_the_markdown_states_the_limits():
    """A document that leaves the building must carry its own caveat. Someone will paste
    this into a pull request and nobody there will have read docs/metrics.md."""
    from revoice.voicemetric import chart

    md = chart.markdown(_reports_for_markdown(), voice="v")
    assert "not an authorship" in md.lower() or "not" in md and "authorship" in md
    assert "AUC 0.67" in md
    assert "register" in md


def test_the_report_page_loads_the_engine_and_is_in_the_nav():
    page = (ROOT / "pages" / "report.html").read_text()
    for script in ("engine-constants.js", "voicemetric.js", "voicespace.js"):
        assert f'src="{script}"' in page, f"report.html does not load {script}"
    assert "'report.html'" in (ROOT / "pages" / "site.js").read_text(), "not in the nav"


@node
def test_the_browser_engine_reports_the_same_versions_as_the_package():
    """The page must not be able to claim a version the package does not have.

    This file is a PORT, so "which engine produced this number" is the question a
    surprising result turns on — and the signature answers whether two results are
    comparable at all, even when no version moved. All of it is generated from
    `revoice.versions()`, and this is the assertion that it stayed generated.
    """
    import revoice

    js = _run_node("process.stdout.write(JSON.stringify({"
                   "versions: vmVersions(), version: vmVersion(), "
                   "info: vmVersionInfo(), sig: vmSignature()}));")
    assert js["versions"] == revoice.versions()
    assert js["version"] == revoice.voicemetric.version()
    assert js["info"] == list(revoice.voicemetric.version_info())
    assert js["sig"] == revoice.voicemetric.signature()


@node
def test_the_pages_version_file_agrees_with_the_engine_constants():
    """Two generated files carry versions; both come from the same call, and this is
    what keeps that true rather than merely intended."""
    import re

    text = (ROOT / "pages" / "version.js").read_text()
    m = re.search(r"var REVOICE_VERSION = (\{.*?\});", text, re.S)
    assert m, "pages/version.js does not define REVOICE_VERSION"
    page = json.loads(m.group(1))

    js = _run_node("process.stdout.write(JSON.stringify(vmVersions()));")
    for key in ("revoice", "voicemetric", "rubric"):
        assert page[key] == js[key], f"{key}: version.js {page[key]} vs engine {js[key]}"
