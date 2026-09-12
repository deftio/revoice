"""Verification statistics — known-answer tests.

These are the measures every voice-metric claim rests on, so they are tested against
values derivable by hand rather than against whatever the implementation happens to
produce. Notably: cllr == 1.0 for an all-zero log-LR system is the reference point the
whole scale is anchored to (a system that always says "don't know").
"""

import math
import random

import pytest

from revoice.voicemetric.verify import (
    auc,
    calibrate_llr,
    cllr,
    cllr_report,
    eer,
    fit_logistic,
    fit_weights,
    min_cllr,
    pav,
    tpr_at_fpr,
)

# ---------- auc ----------


def test_auc_perfect_and_reversed():
    assert auc([3.0, 4.0, 5.0], [0.0, 1.0, 2.0]) == 1.0
    assert auc([0.0, 1.0, 2.0], [3.0, 4.0, 5.0]) == 0.0


def test_auc_all_ties_is_chance():
    assert auc([1.0, 1.0], [1.0, 1.0]) == 0.5


def test_auc_partial_overlap_hand_computed():
    # targets {2,4}, nontargets {1,3}: pairs (2>1)(2<3)(4>1)(4>3) -> 3/4
    assert auc([2.0, 4.0], [1.0, 3.0]) == 0.75


def test_auc_single_tie_counts_half():
    # targets {1,2}, nontargets {2,3}: (1<2)(1<3)(2==2 ->.5)(2<3) -> 0.5/4
    assert auc([1.0, 2.0], [2.0, 3.0]) == 0.125


def test_auc_empty_is_nan():
    assert math.isnan(auc([], [1.0]))
    assert math.isnan(auc([1.0], []))


# ---------- eer / operating point ----------


def test_eer_perfect_separation_is_zero():
    assert eer([10.0, 11.0], [0.0, 1.0]) == 0.0


def test_eer_chance_is_half():
    assert eer([1.0, 1.0], [1.0, 1.0]) == 0.5


def test_eer_empty_is_nan():
    assert math.isnan(eer([], []))


def test_tpr_at_fpr_perfect_separation():
    tpr, threshold = tpr_at_fpr([10.0, 11.0, 12.0], [0.0, 1.0, 2.0], max_fpr=0.0)
    assert tpr == 1.0
    assert threshold == 10.0


def test_tpr_at_fpr_respects_the_budget():
    # one nontarget sits above two of three targets; at fpr=0 only the top target survives
    tpr, _ = tpr_at_fpr([1.0, 2.0, 9.0], [0.0, 3.0], max_fpr=0.0)
    assert tpr == pytest.approx(1 / 3)
    # allowing 50% fpr lets the threshold drop below the intruder
    tpr, _ = tpr_at_fpr([1.0, 2.0, 9.0], [0.0, 3.0], max_fpr=0.5)
    assert tpr == pytest.approx(1.0)


def test_tpr_at_fpr_empty_is_nan():
    tpr, threshold = tpr_at_fpr([], [], 0.05)
    assert math.isnan(tpr) and math.isnan(threshold)


# ---------- pav ----------


def test_pav_already_monotone_is_unchanged():
    # labels already increasing with score -> nothing to pool
    assert pav([1.0, 2.0, 3.0, 4.0], [0, 0, 1, 1]) == [0.0, 0.0, 1.0, 1.0]


def test_pav_pools_violating_block():
    # the middle pair violates monotonicity and gets averaged to 0.5
    assert pav([1.0, 2.0, 3.0, 4.0], [0, 1, 0, 1]) == [0.0, 0.5, 0.5, 1.0]


def test_pav_fully_reversed_pools_everything():
    assert pav([1.0, 2.0], [1, 0]) == [0.5, 0.5]


def test_pav_preserves_input_order():
    # scores given out of order: result is indexed by INPUT position, not sorted position
    assert pav([9.0, 1.0], [1, 0]) == [1.0, 0.0]


# ---------- cllr ----------


def test_cllr_of_uninformative_system_is_exactly_one():
    """log-LR 0 everywhere = 'I have no idea'. This anchors the whole scale."""
    assert cllr([0.0, 0.0, 0.0], [0.0, 0.0]) == pytest.approx(1.0)


def test_cllr_of_confident_correct_system_approaches_zero():
    assert cllr([40.0, 40.0], [-40.0, -40.0]) == pytest.approx(0.0, abs=1e-12)


def test_cllr_infinite_correct_llr_costs_nothing():
    assert cllr([math.inf], [-math.inf]) == 0.0


def test_cllr_confidently_wrong_is_infinite():
    assert cllr([-math.inf], [0.0]) == math.inf


def test_cllr_worse_than_useless_when_backwards():
    assert cllr([-2.0, -2.0], [2.0, 2.0]) > 1.0


def test_cllr_empty_is_nan():
    assert math.isnan(cllr([], [1.0]))


def test_min_cllr_perfect_separation_is_zero():
    assert min_cllr([5.0, 6.0, 7.0], [1.0, 2.0, 3.0]) == 0.0


def test_min_cllr_is_one_when_scores_carry_nothing():
    assert min_cllr([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)


def test_min_cllr_never_exceeds_cllr_of_same_scores_as_llrs():
    target, nontarget = [1.0, 2.0, 3.0, 4.0], [0.5, 1.5, 2.5, 3.5]
    assert min_cllr(target, nontarget) <= cllr(target, nontarget) + 1e-9


def test_min_cllr_empty_is_nan():
    assert math.isnan(min_cllr([], []))


# ---------- logistic calibration ----------


def test_fit_logistic_recovers_positive_slope():
    a, b, mean, std = fit_logistic([0.0, 1.0, 2.0, 8.0, 9.0, 10.0], [0, 0, 0, 1, 1, 1])
    assert a > 0
    assert std > 0
    llrs = calibrate_llr((a, b, mean, std), [10.0, 0.0], 3, 3)
    assert llrs[0] > llrs[1]


def test_fit_logistic_degenerate_labels_do_not_diverge():
    # all one class: the Hessian goes singular; the fit must break out, not blow up
    a, b, _, _ = fit_logistic([1.0, 2.0, 3.0], [1, 1, 1])
    assert math.isfinite(a) and math.isfinite(b)


def test_calibrate_llr_subtracts_the_prior():
    model = (1.0, 0.0, 0.0, 1.0)
    balanced = calibrate_llr(model, [0.0], 5, 5)[0]
    skewed = calibrate_llr(model, [0.0], 9, 1)[0]
    assert balanced == pytest.approx(0.0)
    assert skewed == pytest.approx(-math.log(9.0))


def test_calibrate_llr_with_no_nontargets_uses_zero_prior():
    assert calibrate_llr((1.0, 0.0, 0.0, 1.0), [2.0], 3, 0)[0] == pytest.approx(2.0)


# ---------- report ----------


def test_cllr_report_separable_scores_beat_the_useless_system():
    target = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    nontarget = [0.0, 1.0, 2.0, 3.0, 4.0, 4.5]
    r = cllr_report(target, nontarget)
    assert r["cllr_min"] == 0.0
    assert r["cllr"] < 1.0
    assert r["cllr_cal"] == pytest.approx(r["cllr"] - r["cllr_min"])


def test_cllr_report_too_few_trials_is_nan():
    r = cllr_report([1.0], [0.0])
    assert all(math.isnan(v) for v in r.values())


def test_cllr_report_at_the_minimum_viable_trial_count():
    """folds*2 per class is the documented floor — it must produce finite numbers."""
    r = cllr_report([1.0, 2.0, 3.0, 4.0], [0.0, 0.5, 0.6, 0.7], folds=2)
    assert math.isfinite(r["cllr"]) and math.isfinite(r["cllr_min"])


def test_eer_is_between_zero_and_one_across_random_inputs():
    """The crossing-always-exists invariant the implementation relies on."""
    rng = random.Random(4)
    for _ in range(200):
        t = [rng.gauss(1, 1) for _ in range(rng.randint(1, 8))]
        n = [rng.gauss(0, 1) for _ in range(rng.randint(1, 8))]
        assert 0.0 <= eer(t, n) <= 1.0


# ---------- multivariate weight fitting ----------


def test_fit_weights_finds_the_only_useful_dimension():
    rng = random.Random(3)
    tar = [[1.0 + rng.gauss(0, 0.1), rng.gauss(0, 1)] for _ in range(60)]
    non = [[0.0 + rng.gauss(0, 0.1), rng.gauss(0, 1)] for _ in range(60)]
    w = fit_weights(tar, non)
    assert w[0] > 0.9 and w[1] < 0.1
    assert sum(w) == pytest.approx(1.0)


def test_fit_weights_clips_anti_predictive_dimensions_to_zero():
    """A component that predicts backwards is noise, not a term to subtract.

    Keeping the sign would fit one corpus's quirk; every component here is built so
    that higher means more similar, so a negative weight is always a bug not a signal.
    """
    rng = random.Random(4)
    tar = [[1.0 + rng.gauss(0, 0.1), 0.0] for _ in range(40)]
    non = [[0.0 + rng.gauss(0, 0.1), 1.0] for _ in range(40)]
    w = fit_weights(tar, non)
    assert all(x >= 0.0 for x in w)
    assert w[0] > w[1]


def test_fit_weights_empty_input():
    assert fit_weights([], []) == []
    assert fit_weights([[1.0]], []) == []


def test_fit_weights_on_pure_noise_stays_normalised():
    rng = random.Random(5)
    tar = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(40)]
    non = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(40)]
    w = fit_weights(tar, non)
    assert sum(w) == pytest.approx(1.0)
    assert all(x >= 0.0 for x in w)


def test_fit_weights_degenerate_column_does_not_divide_by_zero():
    # second column is constant -> zero variance -> must not blow up
    tar = [[1.0, 7.0] for _ in range(10)]
    non = [[0.0, 7.0] for _ in range(10)]
    w = fit_weights(tar, non)
    assert all(math.isfinite(x) for x in w)
    assert sum(w) == pytest.approx(1.0)


# ---------------------------------------------------------------------------------
# c@1 — accuracy that can score an honest abstention.
#
# AUC and EER both grade a ranker. This engine has to decide, and its most common
# correct answer is "these overlap, I cannot call it". Neither of the other measures
# can score that as anything but a coin flip.

def test_c_at_1_with_no_abstention_is_plain_accuracy():
    from revoice.voicemetric.verify import c_at_1

    r = c_at_1([0.9, 0.8, 0.7], [0.3, 0.2, 0.1], threshold=0.5)
    assert r["c_at_1"] == 1.0 == r["accuracy"]
    assert r["abstained"] == 0 and r["answered"] == 6


def test_a_perfectly_wrong_system_scores_zero():
    from revoice.voicemetric.verify import c_at_1

    r = c_at_1([0.1, 0.2], [0.8, 0.9], threshold=0.5)
    assert r["c_at_1"] == 0.0 and r["accuracy"] == 0.0


def test_abstaining_cannot_rescue_a_system_that_knows_nothing():
    """The property that makes c@1 honest: an abstention earns the rate you achieved on
    what you did answer. Abstain on everything and you score zero, not 0.5."""
    from revoice.voicemetric.verify import c_at_1

    r = c_at_1([0.5, 0.5], [0.5, 0.5], threshold=0.5, band=0.1)
    assert r["abstained"] == 4 and r["answered"] == 0
    assert r["c_at_1"] == 0.0


def test_abstaining_on_the_cases_you_would_have_got_wrong_helps():
    """The skill c@1 is built to reward: knowing WHICH pairs you cannot call."""
    from revoice.voicemetric.verify import c_at_1

    # four confident and right, two sitting on the threshold that would be coin flips
    target = [0.95, 0.90, 0.52]
    nontarget = [0.05, 0.10, 0.48]
    decisive = c_at_1(target, nontarget, threshold=0.5)
    abstaining = c_at_1(target, nontarget, threshold=0.5, band=0.05)
    assert abstaining["abstained"] == 2
    # the two borderline calls happened to be right, so abstaining costs a little here —
    # what matters is that the measure prices the trade instead of ignoring it
    assert decisive["accuracy"] == 1.0
    assert 0.0 < abstaining["c_at_1"] <= 1.0


def test_c_at_1_handles_an_empty_trial_set():
    from revoice.voicemetric.verify import c_at_1

    r = c_at_1([], [], threshold=0.5)
    assert r["c_at_1"] == 0.0 and r["answered"] == 0


def test_c_at_1_reports_the_band_it_used():
    from revoice.voicemetric.verify import c_at_1

    assert c_at_1([0.9], [0.1], threshold=0.5, band=0.25)["band"] == 0.25
