from revoice.rubric import judge_all, judge_dimension, vote_metrics

RUBRIC = {
    "quality": {
        "description": "test dim",
        "weight": 1.0,
        "choices": {"good": "is good", "bad": "is bad"},
        "scores": {"good": 1.0, "bad": 0.0},
        "reject_below": 0.5,
    }
}


def test_vote_metrics_paper_cases():
    contested = vote_metrics(["a"] * 51 + ["b"] * 49, 2)
    decisive = vote_metrics(["a"] * 95 + ["b"] * 5, 2)
    assert contested["winner"] == decisive["winner"] == "a"
    assert contested["winner_gap"] < 0.1 < decisive["winner_gap"]
    assert abs(contested["n_eff"] - 2.0) < 0.01
    # 50/50 split: a_k depends on k, n_eff does not
    assert vote_metrics(["a", "b"], 2)["a_k"] == 0.0
    assert vote_metrics(["a", "b"], 7)["a_k"] > 0.3
    u = vote_metrics(["a"] * 5, 4)
    assert u["n_eff"] == 1.0 and u["a_k"] == 1.0


def test_judge_scores_computed_in_code():
    r = judge_all(lambda s, u: "good", RUBRIC, candidate="x", original="y")
    assert r["composite"] == 1.0 and not r["rejected_by"]
    r = judge_all(lambda s, u: "The answer is: bad.", RUBRIC, candidate="x")
    assert r["composite"] == 0.0 and r["rejected_by"] == ["quality"]


def test_unparseable_votes_discarded():
    r = judge_dimension(lambda s, u: "banana", "quality", RUBRIC["quality"], "x")
    assert r["choice"] is None and r["score"] is None


def test_majority_voting():
    seq = iter(["good", "bad", "good"])
    r = judge_dimension(lambda s, u: next(seq), "quality", RUBRIC["quality"], "x", k=3)
    assert r["choice"] == "good"
    assert r["agreement"]["winner_share"] == 0.667
    assert r["agreement"]["counts"] == {"good": 2, "bad": 1}
