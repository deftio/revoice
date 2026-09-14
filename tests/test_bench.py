"""The voice-metric bench: corpus loading, trial construction, evaluation, reporting.

The synthetic corpus below is built so the *protocol* is testable independently of how
good the metric happens to be: two authors with deliberately different surface habits,
each with two distinct "works" so work-level leave-one-out has something to hold out.
"""

import json
import math
import random

import pytest
from typer.testing import CliRunner

from revoice.cli import app
from revoice.voicemetric.bench import (
    COMPONENTS,
    WEIGHTS,
    Doc,
    Trial,
    _window,
    bench,
    by_register,
    combine,
    content_control,
    corpus_summary,
    default_scorers,
    evaluate,
    fit_scorer,
    load_corpus,
    parse_name,
    render,
    run_trials,
    split_trials,
    summarize_lengths,
    uniform,
    verdict,
)

runner = CliRunner()

# Two authors with different rhythm, punctuation and lexis; two works each, on
# different subjects, so work-level LOO actually removes the query's topic.
_SENTENCES = {
    ("alpha", "engines"): "The engine turns; the shaft answers, and the governor holds it steady. "
                          "We measured the torque again, and again it drifted low.",
    ("alpha", "harbours"): "The harbour fills; the tide answers, and the seawall holds it steady. "
                           "We sounded the channel again, and again it shoaled inshore.",
    ("beta", "engines"): "Engine performance was evaluated under load. Torque measurements "
                         "indicated a downward drift. Governor stability remained acceptable.",
    ("beta", "harbours"): "Harbour capacity was evaluated under tide. Channel measurements "
                          "indicated a shoaling trend. Seawall stability remained acceptable.",
}


def _corpus(tmp_path, docs_per_work=4, repeats=14):
    root = tmp_path / "corpus"
    for (author, work), sentence in _SENTENCES.items():
        d = root / author / "training-data"
        d.mkdir(parents=True, exist_ok=True)
        for i in range(1, docs_per_work + 1):
            body = " ".join(f"{sentence} Section {i} note {j}." for j in range(repeats))
            (d / f"prose-{work}-{i}.md").write_text(body)
    return root


@pytest.fixture()
def corpus_root(tmp_path):
    return _corpus(tmp_path)


# ---------- corpus ----------


def test_parse_name_convention_and_fallback():
    assert parse_name("fiction-adams-diary-a-01") == ("fiction", "adams-diary")
    assert parse_name("science-origin-4") == ("science", "origin")
    assert parse_name("memoir-autobiography-11") == ("memoir", "autobiography")
    # non-conforming names still load; they just lose topic control
    assert parse_name("notes") == ("unknown", "notes")


def test_load_corpus_reads_authors_works_registers(corpus_root):
    docs = load_corpus(corpus_root)
    assert len(docs) == 16
    assert {d.author for d in docs} == {"alpha", "beta"}
    assert {d.work for d in docs} == {"engines", "harbours"}
    assert {d.register for d in docs} == {"prose"}
    assert all(d.words > 0 for d in docs)


def test_load_corpus_skips_dotfiles_and_unreadable(corpus_root):
    (corpus_root / "alpha" / "training-data" / ".hidden.md").write_text("secret")
    (corpus_root / "alpha" / "training-data" / "img.png").write_bytes(b"\x89PNG")
    (corpus_root / "alpha" / "training-data" / "empty.md").write_text("   ")
    assert len(load_corpus(corpus_root)) == 16


def test_load_corpus_ignores_dirs_without_training_data(corpus_root):
    (corpus_root / "not-a-voice").mkdir()
    assert {d.author for d in load_corpus(corpus_root)} == {"alpha", "beta"}


def test_corpus_summary_shape(corpus_root):
    summary = corpus_summary(load_corpus(corpus_root))
    assert summary["alpha"]["docs"] == 8
    assert summary["alpha"]["works"] == ["engines", "harbours"]
    assert summary["alpha"]["registers"] == {"prose": 8}
    assert summary["alpha"]["chars"] > 0


# ---------- scorers ----------


def test_default_scorers_cover_every_component():
    scorers = default_scorers()
    assert "composite" in scorers
    for c in COMPONENTS:
        assert scorers[c][c] == 1.0
        assert sum(scorers[c].values()) == 1.0


def test_no_vocab_scorer_drops_vocab_and_renormalizes():
    w = default_scorers()["no-vocab"]
    assert w["vocab"] == 0.0
    assert sum(w.values()) == pytest.approx(1.0)


def test_content_free_scorer_excludes_the_topical_component():
    """The content-free ablation is the one docs/metrics.md argues for: no tf-idf."""
    w = default_scorers()["content-free"]
    assert w["vocab"] == 0.0
    assert w["ngram"] == 0.0  # char n-grams pick up topic words too
    assert w["fwbigram"] > 0 and w["delta"] > 0
    assert sum(w.values()) == pytest.approx(1.0)


def test_default_composite_gives_topic_zero_weight():
    """tf-idf measures subject matter; it must never be inside an authorship score."""
    assert default_scorers()["composite"]["vocab"] == 0.0


def test_combine_is_a_weighted_percentage():
    comps = dict.fromkeys(COMPONENTS, 0.5)
    even = dict.fromkeys(COMPONENTS, 1 / len(COMPONENTS))
    assert combine(comps, even) == pytest.approx(50.0)
    assert combine(comps, {"delta": 1.0}) == pytest.approx(50.0)


def test_combine_ignores_unknown_components():
    assert combine({"nonsense": 1.0}, {"delta": 1.0}) == 0.0


# ---------- trials ----------


def test_run_trials_labels_and_topic_control(corpus_root):
    docs = load_corpus(corpus_root)
    trials = run_trials(docs, lengths=(30,), queries_per_cell=5, seed=1, level="work")
    assert trials
    assert {t.same for t in trials} == {True, False}
    for t in trials:
        assert t.same == (t.query_author == t.ref_author)
        assert t.components is not None
        assert set(t.components) >= set(COMPONENTS)


def test_run_trials_is_deterministic_for_a_seed(corpus_root):
    docs = load_corpus(corpus_root)
    kw = {"lengths": (30,), "queries_per_cell": 4, "level": "work"}
    a = run_trials(docs, seed=5, **kw)
    b = run_trials(docs, seed=5, **kw)
    assert [t.components["delta"] for t in a] == [t.components["delta"] for t in b]


def test_run_trials_doc_level_builds_more_reference_models(corpus_root):
    docs = load_corpus(corpus_root)
    work = run_trials(docs, (30,), 3, 1, "work")
    doc = run_trials(docs, (30,), 3, 1, "doc")
    assert len({t.ref_exclude for t in doc}) > len({t.ref_exclude for t in work})


def test_run_trials_skips_lengths_longer_than_any_document(corpus_root):
    docs = load_corpus(corpus_root)
    assert run_trials(docs, lengths=(100_000,), queries_per_cell=3, seed=1) == []


def test_window_returns_none_when_the_text_is_too_short():
    rng = random.Random(0)
    assert _window("one two three", 10, rng) is None
    assert _window("one two three", 3, rng) is None  # needs strictly more words
    assert len(_window("one two three four", 2, rng).split()) == 2


def test_run_trials_needs_two_authors(tmp_path):
    root = tmp_path / "solo"
    d = root / "only" / "training-data"
    d.mkdir(parents=True)
    (d / "prose-a-1.md").write_text("one two three four five six seven eight nine ten. " * 20)
    with pytest.raises(RuntimeError, match="at least 2 authors"):
        run_trials(load_corpus(root), (10,), 2, 1)


def test_run_trials_skips_authors_with_too_few_reference_docs(tmp_path):
    """An author whose every doc is one work has nothing left after work-level LOO."""
    root = _corpus(tmp_path, docs_per_work=1)
    thin = root / "gamma" / "training-data"
    thin.mkdir(parents=True)
    (thin / "prose-solo-1.md").write_text("a b c d e f g h i j. " * 40)
    trials = run_trials(load_corpus(root), (20,), 3, 1, "work")
    assert "gamma" not in {t.ref_author for t in trials}


def test_run_trials_reports_progress(corpus_root):
    seen = []
    run_trials(load_corpus(corpus_root), (30,), 2, 1, "work", lambda i, m: seen.append((i, m)))
    assert seen and all("reference from" in m for _, m in seen)


# ---------- evaluation ----------


def _synthetic_trials(separation: float, n: int = 30, lengths=(50, 100), jitter: float = 1e-4):
    """Trials whose components are set by hand, so evaluation is testable exactly.

    `separation` shifts the two classes apart; `jitter` spreads each class out. Overlap
    (and therefore AUC) is controlled by their ratio: jitter*n >> separation gives a
    measure near chance, separation >> jitter*n gives perfect separation.
    """
    out = []
    for length in lengths:
        for i in range(n):
            out.append(Trial("a", "w", "g", "a", "prose", length, True,
                             dict.fromkeys(COMPONENTS, 0.5 + separation + i * jitter)))
            out.append(Trial("a", "w", "g", "b", "prose", length, False,
                             dict.fromkeys(COMPONENTS, 0.5 - separation + i * jitter)))
    return out


def test_evaluate_perfect_separation_scores_perfectly():
    result = evaluate(_synthetic_trials(0.3), {"x": {"delta": 1.0}}, (50, 100))
    x = result["scorers"]["x"]
    assert x["macro"]["auc"] == 1.0
    assert x["macro"]["cllr_min"] == 0.0
    assert x["macro"]["tpr_at_fpr"] == 1.0
    assert x["by_length"][50]["auc"] == 1.0


def test_evaluate_no_separation_is_chance():
    result = evaluate(_synthetic_trials(0.0), {"x": {"delta": 1.0}}, (50, 100))
    x = result["scorers"]["x"]
    assert x["macro"]["auc"] == pytest.approx(0.5, abs=0.05)
    assert x["macro"]["cllr_min"] == pytest.approx(1.0, abs=0.05)


def test_evaluate_counts_and_coverage():
    result = evaluate(_synthetic_trials(0.2, n=10), {"x": {"delta": 1.0}}, (50, 100))
    assert result["n_trials"] == 40
    assert result["n_same"] == result["n_different"] == 20
    assert result["coverage"][50] == {"n_same": 10, "n_different": 10}


def test_evaluate_reports_empty_lengths_rather_than_inventing_numbers():
    result = evaluate(_synthetic_trials(0.2, lengths=(50,)), {"x": {"delta": 1.0}}, (50, 999))
    assert result["coverage"][999] == {"n_same": 0, "n_different": 0}
    assert math.isnan(result["scorers"]["x"]["by_length"][999]["auc"])
    assert result["scorers"]["x"]["macro"]["auc"] == 1.0  # macro ignores the empty cell


def test_evaluate_macro_is_not_the_pooled_figure():
    """Length-mixed pooling is the thing macro-averaging exists to avoid."""
    trials = []
    for i in range(20):
        trials.append(Trial("a", "w", "g", "a", "p", 50, True, dict.fromkeys(COMPONENTS, 0.10 + i * 1e-3)))
        trials.append(Trial("a", "w", "g", "b", "p", 50, False, dict.fromkeys(COMPONENTS, 0.05 + i * 1e-3)))
        trials.append(Trial("a", "w", "g", "a", "p", 100, True, dict.fromkeys(COMPONENTS, 0.90 + i * 1e-3)))
        trials.append(Trial("a", "w", "g", "b", "p", 100, False, dict.fromkeys(COMPONENTS, 0.85 + i * 1e-3)))
    x = evaluate(trials, {"x": {"delta": 1.0}}, (50, 100))["scorers"]["x"]
    assert x["macro"]["auc"] > x["pooled_length_mixed"]["auc"] - 1e-9
    assert x["auc"] == x["macro"]["auc"]


def test_evaluate_uses_default_scorers_when_none_given():
    result = evaluate(_synthetic_trials(0.2), None, (50, 100))
    assert set(result["scorers"]) == set(default_scorers())


def test_summarize_lengths():
    result = evaluate(_synthetic_trials(0.3), {"composite": {"delta": 1.0}}, (50, 100))
    s = summarize_lengths(result)
    assert s == {"n": 2, "min": 1.0, "max": 1.0, "mean": 1.0, "monotone": True}


def test_summarize_lengths_with_no_data():
    result = evaluate([], {"composite": {"delta": 1.0}}, (50,))
    assert summarize_lengths(result) == {"n": 0}


# ---------- content control ----------


def test_content_control_measures_the_topic_gap():
    # topic-controlled: classes overlap heavily. leaked: they separate cleanly.
    strict = evaluate(_synthetic_trials(0.002, jitter=1e-3), {"x": {"delta": 1.0}}, (50, 100))
    loose = evaluate(_synthetic_trials(0.4), {"x": {"delta": 1.0}}, (50, 100))
    cc = content_control(strict, loose)
    assert cc["x"]["topic_contribution"] > 0
    assert cc["x"]["auc_topic_leaked"] >= cc["x"]["auc_topic_controlled"]


def test_content_control_skips_scorers_missing_from_the_leaky_run():
    strict = evaluate(_synthetic_trials(0.2), {"x": {"delta": 1.0}, "y": {"ngram": 1.0}}, (50,))
    loose = evaluate(_synthetic_trials(0.2), {"x": {"delta": 1.0}}, (50,))
    assert set(content_control(strict, loose)) == {"x"}


def test_content_control_nan_when_a_side_has_no_trials():
    strict = evaluate([], {"x": {"delta": 1.0}}, (50,))
    loose = evaluate(_synthetic_trials(0.2), {"x": {"delta": 1.0}}, (50,))
    assert math.isnan(content_control(strict, loose)["x"]["topic_contribution"])


# ---------- verdict ----------


def test_verdict_empty_result():
    assert verdict({"scorers": {}}) == ["no trials scored"]


def test_verdict_flags_a_beaten_composite():
    trials = _synthetic_trials(0.0, n=20)
    for t in trials:  # make `ngram` separate perfectly while the composite stays at chance
        t.components["ngram"] = 0.9 if t.same else 0.1
    result = evaluate(trials, {"composite": {"delta": 1.0}, "ngram": {"ngram": 1.0}}, (50, 100))
    notes = " ".join(verdict(result))
    assert "beaten by 'ngram'" in notes
    assert "weights are not fit to data" in notes


def test_verdict_flags_near_chance_and_operating_point():
    result = evaluate(_synthetic_trials(0.0), {"composite": {"delta": 1.0}}, (50, 100))
    notes = " ".join(verdict(result))
    assert "at or near chance" in notes
    assert "including the shipped composite" in notes
    assert "OPERATING POINT" in notes
    assert "don't know" in notes


def test_verdict_flags_untested_lengths():
    result = evaluate(_synthetic_trials(0.2, lengths=(50,)), {"composite": {"delta": 1.0}}, (50, 999))
    assert "untested, not passing" in " ".join(verdict(result))


def test_verdict_flags_non_monotonic_length_behaviour():
    trials = []
    for length, sep in ((50, 0.4), (100, 0.4), (200, 0.0)):
        for i in range(20):
            trials.append(Trial("a", "w", "g", "a", "p", length, True,
                                dict.fromkeys(COMPONENTS, 0.5 + sep + i * 1e-4)))
            trials.append(Trial("a", "w", "g", "b", "p", length, False,
                                dict.fromkeys(COMPONENTS, 0.5 - sep + i * 1e-4)))
    result = evaluate(trials, {"composite": {"delta": 1.0}}, (50, 100, 200))
    assert "non-monotonic in length" in " ".join(verdict(result))


def test_verdict_flags_miscalibration():
    result = evaluate(_synthetic_trials(0.02, n=40), {"composite": {"delta": 1.0}}, (50, 100))
    result["scorers"]["composite"]["macro"].update({"cllr": 0.9, "cllr_min": 0.5, "cllr_cal": 0.4})
    assert "miscalibration alone" in " ".join(verdict(result))


def test_verdict_reports_topic_leaks():
    result = evaluate(_synthetic_trials(0.002, jitter=1e-3), {"composite": {"delta": 1.0}}, (50, 100))
    result["content_control"] = {"composite": {"auc_topic_controlled": 0.60,
                                               "auc_topic_leaked": 0.85,
                                               "topic_contribution": 0.25}}
    assert "was subject matter, not voice" in " ".join(verdict(result))


# ---------- end to end ----------


def test_bench_end_to_end(corpus_root):
    result = bench(corpus_root, lengths=(30, 60), queries_per_cell=5, seed=3)
    assert result["corpus"]["alpha"]["docs"] == 8
    assert result["protocol"]["leave_one_out"] == "work"
    assert "composite" in result["scorers"]
    assert "composite" in result["content_control"]
    assert result["verdict"]
    json.dumps(result)  # the report must be serializable


def test_bench_can_skip_content_control(corpus_root):
    result = bench(corpus_root, (30,), 4, 3, skip_content_control=True)
    assert "content_control" not in result


def test_bench_rejects_an_empty_corpus(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(RuntimeError, match="no documents found"):
        bench(tmp_path / "empty")


def test_render_covers_every_section(corpus_root):
    out = render(bench(corpus_root, (30, 60), 5, 3))
    for section in ("CORPUS", "PROTOCOL", "DISCRIMINATION", "CALIBRATION", "CONTENT CONTROL",
                    "VERDICT"):
        assert section in out


def test_render_marks_untested_lengths(corpus_root):
    out = render(bench(corpus_root, (30, 99_999), 4, 3, skip_content_control=True))
    assert "NO TRIALS at 99999w" in out
    assert "—" in out


# ---------- cli ----------


def test_cli_bench_prints_a_report(corpus_root, tmp_path):
    out_file = tmp_path / "bench.json"
    r = runner.invoke(app, ["bench", str(corpus_root), "--lengths", "30,60", "-n", "4",
                            "--no-content-control", "-o", str(out_file)])
    assert r.exit_code == 0, r.output
    assert "DISCRIMINATION" in r.output
    assert json.loads(out_file.read_text())["scorers"]["composite"]


def test_cli_bench_json_output(corpus_root):
    r = runner.invoke(app, ["bench", str(corpus_root), "--lengths", "30", "-n", "3",
                            "--no-content-control", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["protocol"]["seed"] == 17


def test_cli_bench_verbose_progress(corpus_root):
    r = runner.invoke(app, ["bench", str(corpus_root), "--lengths", "30", "-n", "2",
                            "--no-content-control", "--verbose"])
    assert r.exit_code == 0, r.output


def test_cli_bench_rejects_bad_lengths(corpus_root):
    r = runner.invoke(app, ["bench", str(corpus_root), "--lengths", "50,abc"])
    assert r.exit_code == 1
    assert "comma-separated integers" in r.output


def test_cli_bench_rejects_empty_lengths(corpus_root):
    r = runner.invoke(app, ["bench", str(corpus_root), "--lengths", ","])
    assert r.exit_code == 1
    assert "--lengths is empty" in r.output


def test_cli_bench_reports_a_bad_corpus(tmp_path):
    (tmp_path / "nothing").mkdir()
    r = runner.invoke(app, ["bench", str(tmp_path / "nothing")])
    assert r.exit_code == 1
    assert "no documents found" in r.output


def test_doc_words_property():
    assert Doc("a", "w", "r", "p.md", "one two three").words == 3


# ---------- weight fitting ----------


def test_fit_scorer_never_gives_topic_any_weight():
    """`vocab` is excluded from fitting by construction, not by performance.

    It is the strongest single component on every corpus we have, and it is measuring
    subject matter — an unconstrained fitter grabs it and reports a number that will
    not survive the author writing about something new.
    """
    trials = []
    for i in range(30):
        # make vocab a PERFECT separator and everything else noise: a fitter allowed
        # to see it would hand it all the weight
        same = dict.fromkeys(COMPONENTS, 0.5)
        same["vocab"] = 1.0
        diff = dict.fromkeys(COMPONENTS, 0.5)
        diff["vocab"] = 0.0
        trials.append(Trial("a", "w", "g", "a", "p", 50, True, {**same, "delta": 0.9 + i * 1e-4}))
        trials.append(Trial("a", "w", "g", "b", "p", 50, False, {**diff, "delta": 0.1 + i * 1e-4}))
    w = fit_scorer(trials, (50,))
    assert w["vocab"] == 0.0
    assert w["delta"] > 0.5          # it must use the real signal instead
    assert sum(w.values()) == pytest.approx(1.0)


def test_fit_scorer_falls_back_to_defaults_without_trials():
    assert fit_scorer([], (50,)) == dict(WEIGHTS)


def test_split_trials_separates_by_reference_model():
    """Fitting and scoring must not share reference models, or we mark our own homework."""
    trials = [Trial("a", f"w{i}", "g", "a", "p", 50, True, dict.fromkeys(COMPONENTS, 0.5))
              for i in range(6)]
    fit, ev = split_trials(trials)
    fit_keys = {(t.ref_author, t.ref_exclude) for t in fit}
    ev_keys = {(t.ref_author, t.ref_exclude) for t in ev}
    assert fit_keys and ev_keys
    assert not (fit_keys & ev_keys)
    assert len(fit) + len(ev) == len(trials)


def test_bench_fit_reports_weights_and_a_heldout_score(corpus_root):
    result = bench(corpus_root, (30, 60), 6, 3, skip_content_control=True, fit=True)
    assert "fitted" in result["scorers"]
    w = result["fitted_weights"]
    assert set(w) == set(COMPONENTS)
    assert w["vocab"] == 0.0
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-3)
    assert "auc" in result["fitted_heldout"]
    assert "FITTED WEIGHTS" in render(result)


def test_uniform_weights_over_a_subset():
    w = uniform(("delta", "punct"))
    assert w["delta"] == w["punct"] == 0.5
    assert w["ngram"] == 0.0
    assert sum(w.values()) == pytest.approx(1.0)


# ---------- hard negatives ----------


def _two_register_corpus(tmp_path):
    """Two genres, two authors each, two works each — the shape hard negatives need."""
    root = tmp_path / "multi"
    voices = {("a1", "humor"), ("a2", "humor"), ("b1", "science"), ("b2", "science")}
    for author, register in voices:
        d = root / author / "training-data"
        d.mkdir(parents=True)
        for work in ("one", "two"):
            for i in range(1, 4):
                (d / f"{register}-{work}-{i}.md").write_text(
                    f"The {author} sample about {work} number {i}. " * 40)
    return root


def test_hard_negatives_only_draw_from_the_same_register(tmp_path):
    docs = load_corpus(_two_register_corpus(tmp_path))
    reg_of = {d.author: d.register for d in docs}
    trials = run_trials(docs, (20,), 4, 1, "work", negatives="same-register")
    assert trials
    for t in trials:
        if not t.same:
            assert reg_of[t.query_author] == reg_of[t.ref_author], \
                "a different-genre negative slipped into the hard-negative set"


def test_default_negatives_include_cross_register_pairs(tmp_path):
    docs = load_corpus(_two_register_corpus(tmp_path))
    reg_of = {d.author: d.register for d in docs}
    trials = run_trials(docs, (20,), 4, 1, "work", negatives="any")
    cross = [t for t in trials if not t.same and reg_of[t.query_author] != reg_of[t.ref_author]]
    assert cross, "the default mode should mix in the easy cross-genre pairs"


def test_hard_negatives_skip_authors_with_no_same_register_rival(tmp_path):
    root = _two_register_corpus(tmp_path)
    lone = root / "solo" / "training-data"
    lone.mkdir(parents=True)
    for work in ("one", "two"):
        for i in range(1, 4):
            (lone / f"poetry-{work}-{i}.md").write_text(f"A solo line about {work} {i}. " * 40)
    trials = run_trials(load_corpus(root), (20,), 4, 1, "work", negatives="same-register")
    assert "solo" not in {t.ref_author for t in trials}


def test_bench_records_the_negatives_mode(tmp_path):
    result = bench(_two_register_corpus(tmp_path), (20,), 4, 1,
                   skip_content_control=True, negatives="same-register")
    assert result["protocol"]["negatives"] == "same-register"
    assert "same-register negatives" in render(result)


def test_bench_reports_when_no_trials_can_be_built(tmp_path):
    root = tmp_path / "lonely"
    for author in ("x", "y"):
        d = root / author / "training-data"
        d.mkdir(parents=True)
        (d / f"{author}-only-1.md").write_text("one two three four five. " * 40)
    with pytest.raises(RuntimeError, match="no trials"):
        bench(root, (20,), 4, 1, skip_content_control=True)


def test_cli_hard_negatives_flag(corpus_root):
    r = runner.invoke(app, ["bench", str(corpus_root), "--lengths", "30", "-n", "3",
                            "--no-content-control", "--hard-negatives", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["protocol"]["negatives"] == "same-register"


# ---------- per-genre breakdown ----------


def test_by_register_groups_by_the_reference_authors_genre(tmp_path):
    """Authorship is not equally hard in every genre; one aggregate hides that."""
    docs = load_corpus(_two_register_corpus(tmp_path))
    trials = run_trials(docs, (20,), 4, 1, "work", negatives="same-register")
    br = by_register(trials)
    assert set(br) == {"humor", "science"}
    for _reg, v in br.items():
        assert v["authors"] == 2
        assert v["n_same"] > 0 and v["n_different"] > 0


def test_by_register_accepts_a_custom_weighting(tmp_path):
    docs = load_corpus(_two_register_corpus(tmp_path))
    trials = run_trials(docs, (20,), 4, 1, "work")
    assert set(by_register(trials, {"delta": 1.0})) == {"humor", "science"}


def test_by_register_empty_trials():
    assert by_register([]) == {}


def test_render_shows_the_genre_table_only_when_there_is_more_than_one(tmp_path):
    multi = bench(_two_register_corpus(tmp_path), (20,), 4, 1, skip_content_control=True)
    assert "BY GENRE" in render(multi)


def test_render_omits_the_genre_table_for_a_single_genre(corpus_root):
    single = bench(corpus_root, (30,), 4, 3, skip_content_control=True)
    assert len(single["by_register"]) == 1
    assert "BY GENRE" not in render(single)


# ---------- the default text reader ----------


def test_read_text_file_rejects_binary_by_content_not_extension(tmp_path):
    """Sniffing content is the right amount of knowledge for the measurement layer:
    it keeps a stray image out of a corpus without learning what a .docx is."""
    from revoice.voicemetric.bench import read_text_file

    (tmp_path / "png-magic.md").write_bytes(b"\x89PNG\r\n\x1a\n")          # wrong ext, binary
    (tmp_path / "nul.md").write_bytes(b"text\x00more text" + b"x" * 200)   # NUL byte
    (tmp_path / "plain.bin").write_text("ordinary prose, wrong extension.")  # right the other way
    assert read_text_file(tmp_path / "png-magic.md") is None
    assert read_text_file(tmp_path / "nul.md") is None
    assert read_text_file(tmp_path / "plain.bin") == "ordinary prose, wrong extension."


def test_read_text_file_tolerates_a_stray_bad_byte_in_a_long_document(tmp_path):
    f = tmp_path / "mostly-fine.md"
    f.write_bytes(("good text " * 5000).encode() + b"\xff\xfe")
    assert read_text_file_result_is_text(f)


def read_text_file_result_is_text(path):
    from revoice.voicemetric.bench import read_text_file

    out = read_text_file(path)
    return isinstance(out, str) and len(out) > 100


def test_read_text_file_on_a_missing_path(tmp_path):
    from revoice.voicemetric.bench import read_text_file

    assert read_text_file(tmp_path / "not-here.md") is None
    assert read_text_file(tmp_path) is None          # a directory is not readable text


def test_load_corpus_accepts_an_injected_reader(tmp_path):
    """The measurement layer never learns document formats; the caller supplies them."""
    from revoice.voicemetric.bench import load_corpus

    d = tmp_path / "a" / "training-data"
    d.mkdir(parents=True)
    (d / "prose-w-1.md").write_bytes(b"\x00binary")
    assert load_corpus(tmp_path) == []
    docs = load_corpus(tmp_path, read=lambda p: "decoded by the caller's own reader")
    assert len(docs) == 1 and docs[0].text.startswith("decoded")


# ---------------------------------------------------------------------------------
# Length sensitivity.
#
# This exists because `yules_k` used to assert, with no source, that Yule's K does not
# drift with text length. Tweedie & Baayen (1998) found no member of that family
# constant. These tests keep the measurement honest so the claim cannot drift back.

def _length_docs(n: int = 6):
    from revoice.voicemetric.bench import Doc

    # paragraphs long enough that the grid has something to cut
    para = ("The committee reviewed the proposal at length and, after considerable "
            "discussion of the several alternatives before it, resolved to defer a "
            "decision until the following session, when further evidence would be "
            "available to members. ")
    short = "It failed. We fixed it. It passed. Nobody was surprised by any of this. "
    out = []
    for i in range(n):
        body = "\n\n".join((para * 4 if i % 2 else short * 12) for _ in range(6))
        out.append(Doc(author=f"a{i}", work=f"w{i}", register="test",
                       path=f"a{i}/{i}.md", text=body))
    return out


def test_length_sensitivity_reports_every_axis():
    from revoice.voicemetric.bench import length_sensitivity
    from revoice.voicemetric.space import AXIS_NAMES

    r = length_sensitivity(_length_docs(), lengths=(50, 100, 200))
    assert set(r["axes"]) == set(AXIS_NAMES)
    assert r["n_docs"] > 0
    assert set(r["worst_first"]) == set(AXIS_NAMES)


def test_the_two_cutting_regimes_are_not_the_same():
    """Cutting by word count splits paragraphs wherever the count lands, which is what
    `_window` does to build trials. Cutting on paragraph boundaries is what `windows`
    does for the page. The paragraph-shape axes behave completely differently under the
    two, and conflating them is how a dead axis goes unnoticed."""
    from revoice.voicemetric.bench import length_sensitivity

    lengths = (50, 100, 200, 400)
    by_word = length_sensitivity(_length_docs(), lengths=lengths, cut="words")
    by_para = length_sensitivity(_length_docs(), lengths=lengths, cut="paragraphs")
    assert by_word["cut"] == "words" and by_para["cut"] == "paragraphs"
    assert abs(by_word["axes"]["paragraph_length"]["r"]) > \
           abs(by_para["axes"]["paragraph_length"]["r"])


def test_an_unknown_cutting_mode_is_refused():
    from revoice.voicemetric.bench import length_sensitivity

    with pytest.raises(ValueError, match="cut must be"):
        length_sensitivity(_length_docs(), cut="sentences")


def test_documents_too_short_for_the_grid_are_skipped():
    from revoice.voicemetric.bench import Doc, length_sensitivity

    tiny = [Doc(author="a", work="w", register="r", path="a/1.md", text="Two words.")]
    r = length_sensitivity(tiny, lengths=(50, 100))
    assert r["n_docs"] == 0
    # every axis still appears, reported as unmeasurable rather than silently absent
    assert all(v["n_docs"] == 0 for v in r["axes"].values())


def test_min_words_excludes_documents_below_the_floor():
    from revoice.voicemetric.bench import length_sensitivity

    docs = _length_docs()
    assert length_sensitivity(docs, lengths=(50, 100), min_words=10 ** 6)["n_docs"] == 0
    assert length_sensitivity(docs, lengths=(50, 100), min_words=0)["n_docs"] > 0


def test_the_drift_table_flags_a_length_dominated_axis():
    from revoice.voicemetric.bench import length_sensitivity, render_length_sensitivity

    r = length_sensitivity(_length_docs(), lengths=(50, 100, 200, 400), cut="words")
    text = render_length_sensitivity(r)
    assert "length sensitivity" in text
    assert "cut on words" in text
    assert "paragraph_length" in text
    # the point of the whole diagnostic: word-cut spans make this axis a length reading
    assert "length-dominated" in text


def test_decision_quality_is_reported_for_every_cell():
    """c@1 rides alongside AUC in the bench output, so abstention is priced everywhere."""
    from revoice.voicemetric.bench import _decision_quality

    d = _decision_quality([0.9, 0.8, 0.85], [0.2, 0.1, 0.15])
    assert d["accuracy"] == 1.0
    assert 0.0 <= d["c_at_1"] <= 1.0
    assert 0.0 <= d["abstain_rate"] <= 1.0
    assert d["threshold"] is not None


def test_decision_quality_degrades_gracefully_on_a_constant_scorer():
    from revoice.voicemetric.bench import _decision_quality

    d = _decision_quality([0.5, 0.5], [0.5, 0.5])
    assert d["threshold"] is None
    assert d["c_at_1"] != d["c_at_1"]        # nan: nothing to threshold


def test_paragraph_cutting_skips_blank_paragraphs():
    """Corpus files routinely carry trailing or doubled blank lines; a blank must not
    count toward the word budget or the cut lands short."""
    from revoice.voicemetric.bench import _truncate

    # a leading blank line is the case that actually produces an empty split, and
    # corpus files start with one often enough to matter
    text = "\n\nFirst paragraph here.\n\n\n\nSecond paragraph here.\n\nThird one."
    got = _truncate(text.split(), text, 6, "paragraphs")
    assert got.startswith("First paragraph here.")     # not an empty leading paragraph
    assert "\n\n\n" not in got


def test_a_document_that_reaches_only_one_grid_point_is_skipped():
    """One point cannot have a slope, so it contributes nothing and is not counted."""
    from revoice.voicemetric.bench import Doc, length_sensitivity

    short = "word " * 60
    docs = [Doc(author="a", work="w", register="r", path="a/1.md", text=short)]
    # 50 is reachable, 100 is not: one point, no correlation, document skipped
    assert length_sensitivity(docs, lengths=(50, 100))["n_docs"] == 0
    assert length_sensitivity(docs, lengths=(20, 50))["n_docs"] == 1


# ---------------------------------------------------------------------------------
# Interval coverage.
#
# Every report this package emits leads with an interval and argues the interval is the
# honest part. That argument is worth exactly as much as its coverage, which had never
# been measured until these existed.

def _coverage_docs(n: int = 8):
    """Documents with enough paragraphs to split into two halves of three windows each."""
    from revoice.voicemetric.bench import Doc

    long_para = ("The committee reviewed the proposal at some length and, after a "
                 "discussion of the alternatives before it, resolved to defer the "
                 "decision until a later session when further evidence would be to hand. "
                 "Several members dissented from that view and said so at the time. ")
    short_para = ("It failed. We fixed it. It passed. Nobody was much surprised. "
                  "The report went out the same day. ")
    out = []
    for i in range(n):
        paras = [(long_para if (i + j) % 2 else short_para) * 3 for j in range(22)]
        out.append(Doc(author=f"a{i % 3}", work=f"w{i}", register="test",
                       path=f"a{i % 3}/{i}.md", text="\n\n".join(paras)))
    return out


def _population(docs):
    from revoice.voicemetric.space import Population

    return Population.fit([d.text for d in docs])


def test_interval_coverage_reports_both_tests():
    from revoice.voicemetric.bench import interval_coverage

    docs = _coverage_docs()
    r = interval_coverage(docs, _population(docs), levels=(0.8, 0.9), replicates=60)
    assert r["n"] > 0
    assert set(r["null_difference"]) == {0.8, 0.9}
    assert set(r["half_vs_half"]) == {0.8, 0.9}
    for e in r["null_difference"].values():
        assert 0.0 <= e["covered"] <= 1.0


def test_the_half_vs_half_benchmark_is_the_corrected_one_not_the_nominal():
    """The whole point of `expected`: the intuitive test is pessimistic by √2, and
    without the benchmark beside it the raw number reads as a damning result."""
    from revoice.voicemetric.bench import _normal_pair_expectation, interval_coverage

    docs = _coverage_docs()
    r = interval_coverage(docs, _population(docs), levels=(0.9,), replicates=60)
    assert r["half_vs_half"][0.9]["expected"] == pytest.approx(0.755, abs=0.002)
    assert _normal_pair_expectation(0.9) < 0.9        # strictly pessimistic
    assert _normal_pair_expectation(0.5) < _normal_pair_expectation(0.95)


def test_a_wider_nominal_level_covers_at_least_as_often():
    """Bands must nest. They only do because every level shares one bootstrap seed per
    document; separate draws could cross."""
    from revoice.voicemetric.bench import interval_coverage

    docs = _coverage_docs()
    r = interval_coverage(docs, _population(docs), levels=(0.5, 0.95), replicates=80)
    assert r["null_difference"][0.95]["covered"] >= r["null_difference"][0.5]["covered"]
    assert r["half_vs_half"][0.95]["covered"] >= r["half_vs_half"][0.5]["covered"]


def test_documents_without_a_second_work_are_skipped():
    """A region has to hold the document's own work out, or it has read what it scores."""
    from revoice.voicemetric.bench import Doc, interval_coverage

    docs = _coverage_docs()
    only_one_work = [Doc(author="solo", work="w", register="t", path="solo/1.md",
                         text=d.text) for d in docs[:3]]
    r = interval_coverage(only_one_work, _population(docs), levels=(0.9,), replicates=40)
    assert r["n"] == 0
    assert r["null_difference"][0.9]["covered"] != r["null_difference"][0.9]["covered"]


def test_documents_with_too_few_windows_are_skipped():
    from revoice.voicemetric.bench import interval_coverage

    docs = _coverage_docs()
    r = interval_coverage(docs, _population(docs), levels=(0.9,), replicates=40,
                          min_windows=10 ** 4)
    assert r["n"] == 0


def test_the_coverage_table_flags_a_miscalibrated_interval():
    from revoice.voicemetric.bench import render_interval_coverage

    narrow = {"n": 100,
              "null_difference": {0.9: {"nominal": 0.9, "covered": 0.60}},
              "half_vs_half": {0.9: {"nominal": 0.9, "covered": 0.5, "expected": 0.755}},
              "median_width_at_90": 12.0, "median_null_width_at_90": 17.0,
              "misses_low": 10, "misses_high": 30}
    text = render_interval_coverage(narrow)
    assert "too narrow: overconfident" in text
    wide = json.loads(json.dumps(narrow))
    wide["null_difference"] = {"0.9": {"nominal": 0.9, "covered": 0.99}}
    assert "power left unused" in render_interval_coverage(wide)


def test_report_from_windows_is_the_same_estimator_the_report_ships():
    """Coverage must exercise the shipped estimator, not a second copy of its arithmetic."""
    from revoice.voicemetric.space import (
        Population,
        VoiceRegion,
        report_from_windows,
        similarity_report,
        windows,
    )

    docs = _coverage_docs()
    pop = Population.fit([d.text for d in docs])
    region = VoiceRegion.fit("a", [docs[1].text, docs[2].text], pop)
    text = docs[0].text
    zs = [pop.standardize(w) for w in windows(text)]

    direct = report_from_windows(zs, region, words=len(text.split()))
    via_text = similarity_report(text, region, pop)
    assert direct == via_text


def test_a_document_that_splits_into_an_unusable_half_is_skipped():
    """min_windows lets a 5-window document through, but dealing it alternately leaves
    halves of 3 and 2 — and two windows cannot bound their own mean."""
    from revoice.voicemetric.bench import interval_coverage
    from revoice.voicemetric.space import windows

    docs = _coverage_docs()
    trimmed = []
    for d in docs:
        ws = windows(d.text)[:5]
        trimmed.append(type(d)(author=d.author, work=d.work, register=d.register,
                               path=d.path, text="\n\n".join(ws)))
    assert len(windows(trimmed[0].text)) == 5
    r = interval_coverage(trimmed, _population(docs), levels=(0.9,), replicates=40,
                          min_windows=4)
    assert r["n"] == 0
