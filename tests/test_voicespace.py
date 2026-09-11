"""Voice space: named interpretable axes, standardization, regions, dimensionality.

The property that matters throughout is DIRECTION: every axis is built so that a higher
value means more of what the axis name says. If one axis quietly points the other way,
distances stay plausible and every explanation the tool gives is backwards.
"""

import json
import math

import pytest
from typer.testing import CliRunner

from revoice.cli import app
from revoice.voicemetric.space import (
    AXES,
    AXIS_NAMES,
    Population,
    VoiceRegion,
    coordinates,
    correlation_matrix,
    effective_dimensionality,
    eigenvalues,
)

runner = CliRunner()

TERSE = ("The valve failed. We replaced it. The test passed.\n\n"
         "Bench data agreed. No further work is needed.") * 6
ORNATE = ("Although the determination of the operational characteristics of the assembly "
          "was, in the first instance, undertaken with a considerable measure of caution, "
          "the resulting documentation of the observed behaviours; the subsequent "
          "classification of those observations; and the eventual formulation of a "
          "recommendation, were all completed.\n\n") * 6


def test_every_axis_is_produced_and_finite():
    c = coordinates(TERSE)
    assert set(c) == set(AXIS_NAMES)
    assert all(math.isfinite(v) for v in c.values())


def test_axis_metadata_is_complete_and_unique():
    assert len(AXES) == len(AXIS_NAMES) == len(set(AXIS_NAMES))
    for a in AXES:
        assert a.low and a.high and a.family
        assert a.low != a.high


def test_axes_point_the_way_their_names_say():
    """Ornate prose must score higher on the ornate end of every relevant axis."""
    terse, ornate = coordinates(TERSE), coordinates(ORNATE)
    assert ornate["sentence_length"] > terse["sentence_length"]
    assert ornate["word_length"] > terse["word_length"]
    assert ornate["nominalization"] > terse["nominalization"]
    assert ornate["punctuation_variety"] > terse["punctuation_variety"]
    assert ornate["readability"] < terse["readability"]      # higher Flesch = easier


def test_lexical_richness_is_inverted_so_higher_means_richer():
    """Yule's K falls as vocabulary widens; the axis negates it to keep direction uniform."""
    repetitive = "the cat sat on the mat with the cat and the mat and the cat. " * 30
    varied = ("Peculiar amphibians navigated turbulent estuaries while botanists "
              "catalogued unfamiliar specimens beneath sprawling mangroves. ") * 15
    assert coordinates(varied)["lexical_richness"] > coordinates(repetitive)["lexical_richness"]


def test_stance_axes_detect_person_and_informality():
    formal = "The procedure was carried out. The results were recorded. " * 20
    chatty = "I think you'll like it. We can't wait to show you what I've built. " * 20
    assert coordinates(chatty)["first_person"] > coordinates(formal)["first_person"]
    assert coordinates(chatty)["second_person"] > coordinates(formal)["second_person"]
    assert coordinates(chatty)["contraction"] > coordinates(formal)["contraction"]


def test_coordinates_of_a_trivial_text_do_not_explode():
    assert all(math.isfinite(v) for v in coordinates("Hi.").values())


# ---------- population ----------


def test_population_standardizes_to_zero_mean():
    texts = [TERSE, ORNATE, TERSE + ORNATE]
    pop = Population.fit(texts)
    assert pop.n == 3
    means = {a: sum(pop.standardize(t)[a] for t in texts) / 3 for a in AXIS_NAMES}
    assert all(abs(m) < 1e-9 for m in means.values())


def test_population_handles_a_constant_axis():
    """Identical texts give zero variance; the floor must keep this finite, not NaN."""
    pop = Population.fit([TERSE, TERSE])
    z = pop.standardize(TERSE)
    assert all(math.isfinite(v) for v in z.values())


def test_population_round_trips_through_a_dict():
    pop = Population.fit([TERSE, ORNATE])
    back = Population.from_dict(json.loads(json.dumps(pop.to_dict())))
    assert back.n == pop.n
    assert back.standardize(TERSE) == pytest.approx(pop.standardize(TERSE))


def test_standardize_accepts_raw_coordinates_as_well_as_text():
    pop = Population.fit([TERSE, ORNATE])
    assert pop.standardize(coordinates(TERSE)) == pytest.approx(pop.standardize(TERSE))


# ---------- regions ----------


def test_region_is_nearer_its_own_style_than_a_different_one():
    pop = Population.fit([TERSE, ORNATE, TERSE + ORNATE])
    region = VoiceRegion.fit("terse", [TERSE, TERSE + " Also fine."], pop)
    assert region.distance(TERSE, pop) < region.distance(ORNATE, pop)
    assert region.n == 2


def test_region_deviations_are_ordered_by_magnitude_and_signed():
    pop = Population.fit([TERSE, ORNATE, TERSE + ORNATE])
    region = VoiceRegion.fit("terse", [TERSE, TERSE + " Also fine."], pop)
    devs = region.deviations(ORNATE, pop)
    assert [a for a, _ in devs] and len(devs) == len(AXIS_NAMES)
    assert all(abs(devs[i][1]) >= abs(devs[i + 1][1]) for i in range(len(devs) - 1))
    assert dict(devs)["word_length"] > 0        # ornate text uses longer words


def test_unnormalized_distance_ignores_the_voices_own_spread():
    pop = Population.fit([TERSE, ORNATE, TERSE + ORNATE])
    region = VoiceRegion.fit("mixed", [TERSE, ORNATE], pop)
    a = region.distance(ORNATE, pop, normalize=True)
    b = region.distance(ORNATE, pop, normalize=False)
    assert math.isfinite(a) and math.isfinite(b) and a != b


def test_region_accepts_precomputed_z_coordinates():
    pop = Population.fit([TERSE, ORNATE, TERSE + ORNATE])
    region = VoiceRegion.fit("terse", [TERSE, TERSE + " Also fine."], pop)
    z = pop.standardize(ORNATE)
    assert region.distance(z) == pytest.approx(region.distance(ORNATE, pop))
    assert region.deviations(z) == region.deviations(ORNATE, pop)


# ---------- structure of the space ----------


def test_correlation_matrix_is_symmetric_with_unit_diagonal():
    pop = Population.fit([TERSE, ORNATE, TERSE + ORNATE, ORNATE + TERSE])
    samples = [pop.standardize(t) for t in (TERSE, ORNATE, TERSE + ORNATE, ORNATE + TERSE)]
    m = correlation_matrix(samples)
    k = len(AXIS_NAMES)
    assert len(m) == k
    for i in range(k):
        assert m[i][i] == pytest.approx(1.0, abs=1e-6) or m[i][i] == 0.0
        for j in range(k):
            assert m[i][j] == pytest.approx(m[j][i], abs=1e-9)


def test_eigenvalues_of_the_identity_are_all_one():
    ident = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    assert eigenvalues(ident) == pytest.approx([1.0, 1.0, 1.0, 1.0], abs=1e-6)


def test_eigenvalues_of_a_rank_one_matrix_concentrate_in_one_factor():
    """Perfectly correlated axes are one degree of freedom, not four."""
    ones = [[1.0] * 4 for _ in range(4)]
    vals = eigenvalues(ones)
    assert vals[0] == pytest.approx(4.0, abs=1e-3)
    assert all(v < 1e-3 for v in vals[1:])


def test_eigenvalues_of_a_zero_matrix_terminate():
    """No non-zero eigenvalues to report, and it must stop rather than spin."""
    assert eigenvalues([[0.0, 0.0], [0.0, 0.0]]) == []


def test_effective_dimensionality_of_independent_axes_is_the_axis_count():
    """Uncorrelated axes should use their full budget of degrees of freedom."""
    import random

    rng = random.Random(3)
    samples = [{a: rng.gauss(0, 1) for a in AXIS_NAMES} for _ in range(400)]
    ed = effective_dimensionality(samples)
    assert ed["axes"] == len(AXIS_NAMES)
    assert ed["effective"] > len(AXIS_NAMES) * 0.8


def test_effective_dimensionality_of_one_repeated_axis_is_about_one():
    import random

    rng = random.Random(4)
    samples = []
    for _ in range(200):
        v = rng.gauss(0, 1)
        samples.append(dict.fromkeys(AXIS_NAMES, v))   # every axis identical
    ed = effective_dimensionality(samples)
    assert ed["effective"] == pytest.approx(1.0, abs=0.2)
    assert ed["top_share"] > 0.95


def test_effective_dimensionality_needs_enough_samples():
    ed = effective_dimensionality([dict.fromkeys(AXIS_NAMES, 1.0)])
    assert math.isnan(ed["effective"])


def test_effective_dimensionality_of_constant_samples_is_nan():
    samples = [dict.fromkeys(AXIS_NAMES, 1.0) for _ in range(5)]
    assert math.isnan(effective_dimensionality(samples)["effective"])


# ---------- cli ----------


@pytest.fixture()
def space_corpus(tmp_path):
    root = tmp_path / "space"
    for name, body in (("terse", TERSE), ("ornate", ORNATE)):
        d = root / name / "training-data"
        d.mkdir(parents=True)
        for i in range(1, 5):
            (d / f"prose-w{i}-{i}.md").write_text(f"{body}\n\nSection {i} follows here.")
    return root


def test_cli_space_reports_dimensionality_and_groups(space_corpus):
    r = runner.invoke(app, ["space", str(space_corpus), "--top", "5"])
    assert r.exit_code == 0, r.output
    assert "VOICE SPACE" in r.output
    assert "effective dimensionality" in r.output
    assert "terse" in r.output and "ornate" in r.output


def test_cli_space_json(space_corpus):
    r = runner.invoke(app, ["space", str(space_corpus), "--json"])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert set(d["axes"]) == set(AXIS_NAMES)
    assert "terse" in d["groups"]


def test_cli_space_compares_two_corpora(space_corpus, tmp_path):
    other = tmp_path / "other"
    d = other / "reg" / "training-data"
    d.mkdir(parents=True)
    for i in range(1, 5):
        (d / f"reg-w{i}-{i}.md").write_text(ORNATE)
    r = runner.invoke(app, ["space", str(space_corpus), "-c", str(other), "--json"])
    assert r.exit_code == 0, r.output
    assert "[reg]" in json.loads(r.output)["groups"], "second corpus should be bracketed"


def test_cli_space_scores_one_document_against_a_group(space_corpus, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(ORNATE)
    r = runner.invoke(app, ["space", str(space_corpus), "-t", str(draft), "--against", "terse"])
    assert r.exit_code == 0, r.output
    assert "similarity to 'terse'" in r.output


def test_cli_space_document_json_includes_deviations(space_corpus, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(ORNATE)
    r = runner.invoke(app, ["space", str(space_corpus), "-t", str(draft),
                            "--against", "terse", "--json"])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert d["against"] == "terse" and d["distance"] > 0
    assert len(d["deviations"]) == len(AXIS_NAMES)


def test_cli_space_document_without_a_group(space_corpus, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(ORNATE)
    r = runner.invoke(app, ["space", str(space_corpus), "-t", str(draft)])
    assert r.exit_code == 0, r.output
    assert "coordinates" in r.output


def test_cli_space_rejects_an_unknown_group(space_corpus, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(TERSE)
    r = runner.invoke(app, ["space", str(space_corpus), "-t", str(draft), "--against", "nobody"])
    assert r.exit_code == 1
    assert "unknown group" in r.output


def test_cli_space_reports_an_empty_corpus(tmp_path):
    (tmp_path / "empty").mkdir()
    r = runner.invoke(app, ["space", str(tmp_path / "empty")])
    assert r.exit_code == 1
    assert "no documents found" in r.output


# ---------- similarity with confidence intervals ----------


def _long(seed_text, n=10):
    return "\n\n".join(f"{seed_text} Passage {i} continues the same manner of writing."
                       for i in range(n))


def test_windows_split_on_paragraphs_and_absorb_a_runt():
    from revoice.voicemetric.space import windows

    text = "\n\n".join(f"{'word ' * 120}end." for _ in range(5))
    ws = windows(text, target_words=220)
    assert len(ws) >= 2
    assert all(w.strip() for w in ws)
    assert windows("") == []


def test_axis_similarity_is_one_at_the_centre_and_falls_away():
    pop = Population.fit([_long(TERSE), _long(ORNATE), TERSE + ORNATE])
    region = VoiceRegion.fit("terse", [_long(TERSE), _long(TERSE)], pop)
    from revoice.voicemetric.space import axis_similarity

    at_centre = axis_similarity(region.centroid, region)
    assert all(v == pytest.approx(1.0) for v in at_centre.values())
    away = axis_similarity(pop.standardize(_long(ORNATE)), region)
    assert all(0.0 < v <= 1.0 for v in away.values())


def test_similarity_report_shape_and_bounds():
    from revoice.voicemetric.space import similarity_report

    pop = Population.fit([_long(TERSE), _long(ORNATE), TERSE + ORNATE])
    region = VoiceRegion.fit("terse", [_long(TERSE), _long(TERSE) + " More."], pop)
    r = similarity_report(_long(TERSE), region, pop, replicates=60)
    assert 0 <= r["overall"] <= 100
    assert r["low"] <= r["overall"] <= r["high"]
    assert set(r["axes"]) == set(AXIS_NAMES)
    for d in r["axes"].values():
        assert 0 <= d["low"] <= d["similarity"] <= d["high"] <= 1.0 + 1e-9


def test_similarity_report_scores_its_own_voice_above_a_different_one():
    from revoice.voicemetric.space import similarity_report

    pop = Population.fit([_long(TERSE), _long(ORNATE), TERSE + ORNATE])
    region = VoiceRegion.fit("terse", [_long(TERSE), _long(TERSE) + " More."], pop)
    assert (similarity_report(_long(TERSE), region, pop, replicates=60)["overall"]
            > similarity_report(_long(ORNATE), region, pop, replicates=60)["overall"])


def test_similarity_report_marks_a_short_text_as_having_no_interval():
    """One window cannot estimate its own variability — say so rather than fake a band."""
    from revoice.voicemetric.space import similarity_report

    pop = Population.fit([_long(TERSE), _long(ORNATE)])
    region = VoiceRegion.fit("terse", [_long(TERSE), _long(TERSE) + " More."], pop)
    r = similarity_report("A single short line of prose here.", region, pop, replicates=40)
    assert r["interval_reliable"] is False
    assert r["low"] == r["overall"] == r["high"]


def test_similarity_report_is_deterministic_for_a_seed():
    from revoice.voicemetric.space import similarity_report

    pop = Population.fit([_long(TERSE), _long(ORNATE), TERSE + ORNATE])
    region = VoiceRegion.fit("terse", [_long(TERSE), _long(TERSE) + " More."], pop)
    kw = {"replicates": 50, "seed": 5}
    a = similarity_report(_long(ORNATE), region, pop, **kw)
    b = similarity_report(_long(ORNATE), region, pop, **kw)
    assert (a["low"], a["high"]) == (b["low"], b["high"])


def test_wider_confidence_gives_a_wider_interval():
    from revoice.voicemetric.space import similarity_report

    pop = Population.fit([_long(TERSE), _long(ORNATE), TERSE + ORNATE])
    region = VoiceRegion.fit("mixed", [_long(TERSE), _long(ORNATE)], pop)
    narrow = similarity_report(_long(ORNATE), region, pop, replicates=200, confidence=0.5)
    wide = similarity_report(_long(ORNATE), region, pop, replicates=200, confidence=0.98)
    assert (wide["high"] - wide["low"]) >= (narrow["high"] - narrow["low"])


def test_percentile_interpolates():
    from revoice.voicemetric.space import _percentile

    assert _percentile([0.0, 10.0], 0.5) == pytest.approx(5.0)
    assert _percentile([0.0, 10.0], 0.0) == 0.0
    assert _percentile([0.0, 10.0], 1.0) == 10.0
    assert math.isnan(_percentile([], 0.5))


# ---------- chart ----------


def _report_for_chart(reliable=True):
    from revoice.voicemetric.space import similarity_report

    pop = Population.fit([_long(TERSE), _long(ORNATE), TERSE + ORNATE])
    region = VoiceRegion.fit("terse", [_long(TERSE), _long(TERSE) + " More."], pop)
    return similarity_report(_long(ORNATE) if reliable else "Short.", region, pop, replicates=60)


def test_chart_is_well_formed_svg():
    import xml.dom.minidom as minidom

    from revoice.voicemetric import chart as voicechart

    svg = voicechart.render(_report_for_chart(), title="T", subtitle="S")
    minidom.parseString(svg)          # raises if malformed
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")


def test_chart_names_every_axis_and_carries_numbers_not_just_colour():
    from revoice.voicemetric import chart as voicechart

    svg = voicechart.render(_report_for_chart())
    for axis in AXIS_NAMES:
        assert axis in svg, axis
    assert "interval" in svg


def test_chart_states_when_there_is_no_interval():
    from revoice.voicemetric import chart as voicechart

    svg = voicechart.render(_report_for_chart(reliable=False))
    assert "no interval" in svg


def test_chart_escapes_markup_in_the_title():
    from revoice.voicemetric import chart as voicechart

    svg = voicechart.render(_report_for_chart(), title='<script>&"x"')
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_chart_colours_are_themeable_custom_properties():
    """Inlined into a themed page the chart must not stay a white slab."""
    from revoice.voicemetric import chart as voicechart

    svg = voicechart.render(_report_for_chart())
    assert "var(--vc-ink" in svg and "var(--vc-near" in svg


def test_chart_verdict_covers_each_band():
    from revoice.voicemetric.chart import _verdict

    base = {"low": 0, "high": 0, "interval_reliable": True}
    assert "inconclusive" in _verdict({**base, "low": 10, "high": 60})[0]
    assert "consistently close" in _verdict({**base, "low": 60, "high": 70})[0]
    assert "consistently distant" in _verdict({**base, "low": 10, "high": 30})[0]
    assert "moderate" in _verdict({**base, "low": 45, "high": 52})[0]
    assert "too short" in _verdict({**base, "interval_reliable": False})[0]


def test_cli_space_writes_a_chart(space_corpus, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(ORNATE)
    out = tmp_path / "chart.svg"
    r = runner.invoke(app, ["space", str(space_corpus), "-t", str(draft),
                            "--against", "terse", "--svg", str(out), "--replicates", "40"])
    assert r.exit_code == 0, r.output
    assert out.is_file() and out.read_text().startswith("<svg")
    assert "chart:" in r.output


def test_cli_space_svg_requires_a_comparison(space_corpus, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(ORNATE)
    r = runner.invoke(app, ["space", str(space_corpus), "-t", str(draft),
                            "--svg", str(tmp_path / "x.svg")])
    assert r.exit_code == 1
    assert "needs --against" in r.output


def test_cli_space_json_includes_the_interval(space_corpus, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(ORNATE)
    r = runner.invoke(app, ["space", str(space_corpus), "-t", str(draft),
                            "--against", "terse", "--json", "--replicates", "40"])
    assert r.exit_code == 0, r.output
    sim = json.loads(r.output)["similarity"]
    assert sim["low"] <= sim["overall"] <= sim["high"]


# ---------- the full HTML report ----------


def _three_reports():
    from revoice.voicemetric.space import similarity_report

    pop = Population.fit([_long(TERSE), _long(ORNATE), TERSE + ORNATE])
    region = VoiceRegion.fit("terse", [_long(TERSE), _long(TERSE) + " More."], pop)
    return [("close", "same style", similarity_report(_long(TERSE), region, pop, replicates=60)),
            ("far", "other style", similarity_report(_long(ORNATE), region, pop, replicates=60)),
            ("short", "no interval", similarity_report("Tiny.", region, pop, replicates=60))]


def test_overlap_is_the_shared_span_of_two_intervals():
    from revoice.voicemetric.chart import overlap

    a = {"low": 30.0, "high": 50.0, "interval_reliable": True}
    b = {"low": 45.0, "high": 60.0, "interval_reliable": True}
    assert overlap(a, b) == pytest.approx(5.0)
    apart = {"low": 70.0, "high": 80.0, "interval_reliable": True}
    assert overlap(a, apart) < 0            # negative means clear of each other
    assert math.isnan(overlap(a, {**b, "interval_reliable": False}))


def test_worst_overlap_finds_the_least_defensible_comparison():
    from revoice.voicemetric.chart import worst_overlap

    reports = [{"low": 0.0, "high": 10.0, "interval_reliable": True},
               {"low": 9.0, "high": 20.0, "interval_reliable": True},
               {"low": 50.0, "high": 60.0, "interval_reliable": True}]
    a, b, ov = worst_overlap(reports)
    assert ov == pytest.approx(1.0)
    assert {a["low"], b["low"]} == {0.0, 9.0}
    assert worst_overlap([{"low": 1.0, "high": 2.0, "interval_reliable": False}]) is None


def test_report_is_self_contained_html():
    """No scripts, no network: it must open from a file, in an email, in five years."""
    from revoice.voicemetric import chart as voicechart

    html = voicechart.report(_three_reports(), voice="terse", engine="voicemetric 0.0.0")
    assert html.startswith("<!doctype html>") and html.rstrip().endswith("</html>")
    assert "<script" not in html.lower()
    # nothing that FETCHES. The SVG xmlns is an identifier, never a request, so the
    # check is on the attributes and CSS constructs that actually reach the network.
    for fetcher in (" src=", " href=", "@import", "url("):
        assert fetcher not in html, f"report would fetch something: {fetcher!r}"
    assert "@media (prefers-color-scheme: dark)" in html, "must survive a dark viewer"


def test_report_puts_every_reading_on_one_rail():
    from revoice.voicemetric import chart as voicechart

    items = _three_reports()
    html = voicechart.report(items, voice="terse")
    assert html.count('class="rrow"') == len(items)
    for label, _, _ in items:
        assert label in html
    assert html.count("<figure>") == len(items), "one axis chart per sample"


def test_report_states_the_overlap_rather_than_leaving_it_to_be_noticed():
    from revoice.voicemetric import chart as voicechart

    overlapping = [("a", "x", {**_three_reports()[0][2], "overall": 50.0, "low": 40.0, "high": 60.0}),
                   ("b", "y", {**_three_reports()[0][2], "overall": 52.0, "low": 42.0, "high": 62.0})]
    html = voicechart.report(overlapping, voice="v")
    assert "pts overlap" in html
    assert "is not evidence" in html


def test_report_says_when_nothing_overlaps():
    from revoice.voicemetric import chart as voicechart

    base = _three_reports()[0][2]
    apart = [("a", "x", {**base, "overall": 20.0, "low": 15.0, "high": 25.0}),
             ("b", "y", {**base, "overall": 80.0, "low": 75.0, "high": 85.0})]
    assert "no overlap" in voicechart.report(apart, voice="v")


def test_report_says_when_no_interval_could_be_measured():
    from revoice.voicemetric import chart as voicechart

    base = _three_reports()[0][2]
    short = [("a", "x", {**base, "interval_reliable": False}),
             ("b", "y", {**base, "interval_reliable": False})]
    html = voicechart.report(short, voice="v")
    assert "no intervals" in html and "impressions" in html


def test_report_escapes_labels():
    from revoice.voicemetric import chart as voicechart

    items = [("<script>x</script>", "&sub", _three_reports()[0][2])]
    html = voicechart.report(items, voice="v")
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_cli_space_writes_a_multi_sample_report(space_corpus, tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(_long(TERSE))
    b.write_text(_long(ORNATE))
    out = tmp_path / "report.html"
    r = runner.invoke(app, ["space", str(space_corpus), "--against", "terse",
                            "-t", str(a), "-t", str(b), "--report", str(out),
                            "--replicates", "40"])
    assert r.exit_code == 0, r.output
    assert out.is_file() and out.read_text().startswith("<!doctype html>")
    assert "2 sample(s) vs 'terse'" in r.output
    assert "report:" in r.output


def test_cli_multi_sample_needs_a_voice_to_compare_against(space_corpus, tmp_path):
    a = tmp_path / "a.md"
    a.write_text(_long(TERSE))
    r = runner.invoke(app, ["space", str(space_corpus), "-t", str(a),
                            "--report", str(tmp_path / "x.html")])
    assert r.exit_code == 1
    assert "need --against" in r.output


def test_cli_multi_sample_rejects_an_unknown_voice(space_corpus, tmp_path):
    a = tmp_path / "a.md"
    a.write_text(_long(TERSE))
    r = runner.invoke(app, ["space", str(space_corpus), "-t", str(a), "--against", "nobody",
                            "--report", str(tmp_path / "x.html")])
    assert r.exit_code == 1
    assert "unknown group" in r.output


def test_cli_multi_sample_json(space_corpus, tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(_long(TERSE))
    b.write_text(_long(ORNATE))
    r = runner.invoke(app, ["space", str(space_corpus), "--against", "terse",
                            "-t", str(a), "-t", str(b), "--json", "--replicates", "40"])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert d["against"] == "terse" and len(d["samples"]) == 2
    assert all("file" in s and "overall" in s for s in d["samples"])


def test_cli_warns_at_the_terminal_when_the_ordering_is_not_evidence(space_corpus, tmp_path):
    """The rail says it on the page; the CLI must say it in the terminal too, or someone
    reads two numbers off stdout and draws the conclusion the intervals forbid."""
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    body = _long(TERSE)
    a.write_text(body)
    b.write_text(body + "\n\nA further passage in the very same manner of writing.")
    out = tmp_path / "r.html"
    r = runner.invoke(app, ["space", str(space_corpus), "--against", "terse",
                            "-t", str(a), "-t", str(b), "--report", str(out),
                            "--replicates", "120"])
    assert r.exit_code == 0, r.output
    assert "overlaps by" in r.output and "not evidence" in r.output
