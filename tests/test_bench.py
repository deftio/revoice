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
from revoice.core.bench import (
    COMPONENTS,
    Doc,
    Trial,
    _window,
    bench,
    combine,
    content_control,
    corpus_summary,
    default_scorers,
    evaluate,
    load_corpus,
    parse_name,
    render,
    run_trials,
    summarize_lengths,
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


def test_no_vocab_rhythm_shape_drops_all_three():
    w = default_scorers()["no-vocab-rhythm-shape"]
    assert w["vocab"] == w["rhythm"] == w["shape"] == 0.0
    assert sum(w.values()) == pytest.approx(1.0)


def test_combine_is_a_weighted_percentage():
    comps = dict.fromkeys(COMPONENTS, 0.5)
    assert combine(comps, dict.fromkeys(COMPONENTS, 1 / 6)) == pytest.approx(50.0)
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
            out.append(Trial("a", "w", "a", "prose", length, True,
                             dict.fromkeys(COMPONENTS, 0.5 + separation + i * jitter)))
            out.append(Trial("a", "w", "b", "prose", length, False,
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
        trials.append(Trial("a", "w", "a", "p", 50, True, dict.fromkeys(COMPONENTS, 0.10 + i * 1e-3)))
        trials.append(Trial("a", "w", "b", "p", 50, False, dict.fromkeys(COMPONENTS, 0.05 + i * 1e-3)))
        trials.append(Trial("a", "w", "a", "p", 100, True, dict.fromkeys(COMPONENTS, 0.90 + i * 1e-3)))
        trials.append(Trial("a", "w", "b", "p", 100, False, dict.fromkeys(COMPONENTS, 0.85 + i * 1e-3)))
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
            trials.append(Trial("a", "w", "a", "p", length, True,
                                dict.fromkeys(COMPONENTS, 0.5 + sep + i * 1e-4)))
            trials.append(Trial("a", "w", "b", "p", length, False,
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
