"""Verification statistics: how well does a score separate same-author from different-author?

Pure stdlib, no numpy. These are the standard measures from speaker/author verification
(the forensic-science lineage, via the BOSARIS toolkit):

  auc          rank-based separation, threshold-free. 0.5 = chance, 1.0 = perfect.
  eer          equal error rate — the FPR where FPR == FNR. Lower is better.
  tpr_at_fpr   the OPERATING POINT. For minimal-touch we care about one question:
               at a false-positive rate we can live with (rewriting foreign text we
               should have left alone is cheap; rewriting the author's own text is
               the expensive error), how much of the author's own writing do we keep?
  cllr         log-likelihood-ratio cost, in bits. Unlike AUC it punishes BAD
               CALIBRATION as well as bad ranking — a system that is confidently
               wrong scores worse than one that is honestly uncertain. Decomposes:
                   cllr      = cost as actually delivered
                   cllr_min  = the floor after ideal (PAV) calibration — pure discrimination
                   cllr_cal  = cllr - cllr_min — how much we lose to miscalibration alone
               Cllr = 1.0 is the useless system (always answer "don't know").

Why calibration and not just AUC: revoice's threshold is a decision, not a ranking.
`stats` reports a number to a human and `pipeline` compares it to a floor. A measure
can rank well (high AUC) while its absolute values mean nothing — which is exactly the
failure mode documented in docs/metrics.md §1.1, where a band calibrated on documents
was applied to spans.
"""

from __future__ import annotations

import math

# ---------- separation ----------


def auc(target: list[float], nontarget: list[float]) -> float:
    """Area under the ROC curve, via the Mann-Whitney U statistic (ties get average ranks).

    P(a random same-author trial scores above a random different-author trial).
    """
    if not target or not nontarget:
        return float("nan")
    data = sorted([(s, 1) for s in target] + [(s, 0) for s in nontarget], key=lambda x: x[0])
    ranks = [0.0] * len(data)
    i = 0
    while i < len(data):
        j = i
        while j + 1 < len(data) and data[j + 1][0] == data[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank over the tied block
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    n1, n0 = len(target), len(nontarget)
    rank_sum = sum(r for r, (_, label) in zip(ranks, data, strict=True) if label == 1)
    return (rank_sum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def _roc_points(target: list[float], nontarget: list[float]):
    """Yield (threshold, tpr, fpr) sweeping the threshold from permissive to strict."""
    thresholds = sorted({*target, *nontarget}, reverse=True)
    n1, n0 = len(target), len(nontarget)
    for t in thresholds:
        tpr = sum(1 for s in target if s >= t) / n1
        fpr = sum(1 for s in nontarget if s >= t) / n0
        yield t, tpr, fpr


def eer(target: list[float], nontarget: list[float]) -> float:
    """Equal error rate: the operating point where miss rate == false-alarm rate.

    The ROC of a finite sample is a staircase, and the crossing point usually falls on
    a segment rather than a corner — so we interpolate. Taking the best corner instead
    reports EER 1.0 for an all-ties system whose ROC is the diagonal and whose true EER
    is 0.5, which would make an uninformative measure look maximally bad rather than
    exactly uninformative.
    """
    if not target or not nontarget:
        return float("nan")
    # (fpr, fnr), walking the threshold from strictest (reject everything) downward.
    # The walk starts at (0, 1) where fnr - fpr = +1 and ends at (1, 0) where it is -1,
    # so the difference changes sign on exactly one segment and the loop always returns.
    points = [(0.0, 1.0)]
    for _, tpr, fpr in _roc_points(target, nontarget):
        points.append((fpr, 1.0 - tpr))

    prev_fpr, prev_fnr = points[0]
    for fpr, fnr in points[1:]:
        before, after = prev_fnr - prev_fpr, fnr - fpr
        if before * after <= 0:  # the curves cross on this segment
            alpha = before / (before - after)
            return prev_fpr + alpha * (fpr - prev_fpr)
        prev_fpr, prev_fnr = fpr, fnr
    raise AssertionError(  # pragma: no cover - invariant documented above
        "unreachable: fnr - fpr must change sign between (0,1) and (1,0)")


def tpr_at_fpr(target: list[float], nontarget: list[float], max_fpr: float = 0.05
               ) -> tuple[float, float]:
    """Best true-positive rate achievable without exceeding `max_fpr`.

    Returns (tpr, threshold). This is the number `pipeline.py` should be built on:
    'keep this fraction of the author's own text untouched, while wrongly leaving
    at most max_fpr of foreign text untouched'.
    """
    if not target or not nontarget:
        return float("nan"), float("nan")
    best = (0.0, float("inf"))
    for t, tpr, fpr in _roc_points(target, nontarget):
        if fpr <= max_fpr and tpr > best[0]:
            best = (tpr, t)
    return best


# ---------- calibration ----------


def _softplus(x: float) -> float:
    """log(1 + e^x), numerically stable at both tails."""
    if x == math.inf:
        return math.inf
    if x == -math.inf:
        return 0.0
    return x + math.log1p(math.exp(-x)) if x > 0 else math.log1p(math.exp(x))


def cllr(target_llr: list[float], nontarget_llr: list[float]) -> float:
    """Log-likelihood-ratio cost in bits, given *calibrated* log-LRs (natural log).

    0 = perfect, 1 = the useless-but-honest system, >1 = worse than saying nothing.
    """
    if not target_llr or not nontarget_llr:
        return float("nan")
    miss = sum(_softplus(-x) for x in target_llr) / len(target_llr)
    false_alarm = sum(_softplus(x) for x in nontarget_llr) / len(nontarget_llr)
    return (miss + false_alarm) / (2.0 * math.log(2.0))


def c_at_1(target: list[float], nontarget: list[float], threshold: float,
           band: float = 0.0) -> dict:
    """PAN's c@1 — accuracy that does not punish an honest "I cannot tell".

    Plain accuracy forces a call on every pair, so a system with wide confidence
    intervals is scored as though it had guessed, and the guess is right half the time.
    AUC has the same blind spot from the other side: it ranks, and ranking has no way to
    express abstention at all. Both of them grade this engine on a behaviour it should
    not have. Overlapping intervals are our most common *correct* output — the rail says
    so in words — and neither metric can score that as anything but a coin flip.

    c@1 (Penas & Rodrigo 2011, adopted by the PAN authorship-verification task) is:

        c@1 = (n_c + n_u * n_c / n) / n

    where `n_c` is the number answered correctly, `n_u` the number left unanswered, and
    `n` the total. An abstention earns the rate you achieved on the questions you did
    answer. So abstaining costs nothing if you were going to be right by luck, and gains
    nothing if you were already accurate — it rewards knowing *which* pairs you cannot
    call, which is precisely the skill a calibrated system has and an overconfident one
    does not.

    `band` is the half-width of the abstention zone around `threshold`: scores within it
    are non-answers. band=0 makes this ordinary accuracy.
    """
    n_c = n_u = 0
    for score, is_target in [(s, True) for s in target] + [(s, False) for s in nontarget]:
        if abs(score - threshold) <= band:
            n_u += 1
        elif (score > threshold) == is_target:
            n_c += 1
    n = len(target) + len(nontarget)
    if n == 0:
        return {"c_at_1": 0.0, "accuracy": 0.0, "answered": 0, "abstained": 0, "band": band}
    return {
        "c_at_1": round((n_c + n_u * n_c / n) / n, 4),
        # the same system scored the old way, so the cost of abstaining is visible
        "accuracy": round(n_c / n, 4),
        "answered": n - n_u,
        "abstained": n_u,
        "band": band,
    }


def pav(scores: list[float], labels: list[int]) -> list[float]:
    """Pool-adjacent-violators isotonic regression: scores -> monotone posteriors.

    The classic PAV: sort by score, then repeatedly merge any adjacent block whose
    mean violates monotonicity. Gives the best posteriors ANY monotone calibration
    of these scores could produce — hence the discrimination floor, cllr_min.
    """
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    blocks: list[list[float]] = []  # [sum_of_labels, count]
    for i in order:
        blocks.append([float(labels[i]), 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            total, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += count
    flat: list[float] = []
    for total, count in blocks:
        flat.extend([total / count] * int(count))
    out = [0.0] * len(scores)
    for position, i in enumerate(order):
        out[i] = flat[position]
    return out


def _posteriors_to_llr(posteriors: list[float], n_target: int, n_nontarget: int) -> list[float]:
    """Strip the empirical prior out of PAV posteriors to recover log-LRs."""
    log_prior_odds = math.log(n_target / n_nontarget) if n_nontarget else 0.0
    out = []
    for p in posteriors:
        if p <= 0.0:
            out.append(-math.inf)
        elif p >= 1.0:
            out.append(math.inf)
        else:
            out.append(math.log(p / (1.0 - p)) - log_prior_odds)
    return out


def min_cllr(target: list[float], nontarget: list[float]) -> float:
    """cllr after ideal (PAV) calibration — the pure discrimination cost of these scores."""
    if not target or not nontarget:
        return float("nan")
    scores = list(target) + list(nontarget)
    labels = [1] * len(target) + [0] * len(nontarget)
    llrs = _posteriors_to_llr(pav(scores, labels), len(target), len(nontarget))
    return cllr(llrs[: len(target)], llrs[len(target):])


def fit_logistic(scores: list[float], labels: list[int], iters: int = 60
                 ) -> tuple[float, float, float, float]:
    """Fit p = sigmoid(a*z + b) on standardized scores, by Newton-Raphson (2 params).

    Returns (a, b, mean, std) — the calibration model. Standardizing first keeps the
    Hessian well conditioned whatever the score's natural range (0-100, or a negative
    distance, or a cosine).
    """
    n = len(scores)
    mean = sum(scores) / n
    var = sum((s - mean) ** 2 for s in scores) / n
    std = math.sqrt(var) or 1.0
    z = [(s - mean) / std for s in scores]

    a, b = 0.0, 0.0
    for _ in range(iters):
        g_a = g_b = h_aa = h_ab = h_bb = 0.0
        for zi, yi in zip(z, labels, strict=True):
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, a * zi + b))))
            r = yi - p
            w = max(p * (1.0 - p), 1e-9)
            g_a += r * zi
            g_b += r
            h_aa += w * zi * zi
            h_ab += w * zi
            h_bb += w
        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-12:
            break
        da = (h_bb * g_a - h_ab * g_b) / det
        db = (h_aa * g_b - h_ab * g_a) / det
        a, b = a + da, b + db
        if abs(da) < 1e-9 and abs(db) < 1e-9:
            break
    return a, b, mean, std


def calibrate_llr(model: tuple[float, float, float, float], scores: list[float],
                  n_target: int, n_nontarget: int) -> list[float]:
    """Apply a fitted logistic model to scores, returning prior-free log-LRs."""
    a, b, mean, std = model
    log_prior_odds = math.log(n_target / n_nontarget) if n_nontarget else 0.0
    return [a * ((s - mean) / std) + b - log_prior_odds for s in scores]


def fit_weights(target_vectors: list[list[float]], nontarget_vectors: list[list[float]],
                iters: int = 250, l2: float = 1.0) -> list[float]:
    """Multivariate logistic fit: which components actually separate the classes?

    Returns one non-negative weight per input dimension, normalised to sum to 1, so
    the result drops straight into a weighted composite. Gradient ascent on the
    penalised log-likelihood — deliberately plain arithmetic, because the whole point
    of this module is that it has no dependencies.

    Two deliberate choices:
      * L2 penalty. With a handful of reference documents the components are highly
        correlated and an unpenalised fit will hand one of them a huge weight and its
        neighbour an offsetting negative one, which is unstable across seeds.
      * Negative weights are clipped to zero. A component that is anti-predictive is
        telling us it is noise, not that we should subtract it; keeping the sign would
        fit the quirks of one corpus.
    """
    if not target_vectors or not nontarget_vectors:
        return []
    dim = len(target_vectors[0])
    xs = target_vectors + nontarget_vectors
    ys = [1.0] * len(target_vectors) + [0.0] * len(nontarget_vectors)

    # standardize so no component dominates through scale alone
    means, sds = [], []
    for j in range(dim):
        col = [x[j] for x in xs]
        m = sum(col) / len(col)
        v = sum((c - m) ** 2 for c in col) / len(col)
        means.append(m)
        sds.append(math.sqrt(v) or 1.0)
    zs = [[(x[j] - means[j]) / sds[j] for j in range(dim)] for x in xs]

    w = [0.0] * dim
    b = 0.0
    lr = 0.5 / max(len(zs), 1)
    for _ in range(iters):
        gw = [0.0] * dim
        gb = 0.0
        for z, y in zip(zs, ys, strict=True):
            dot = b + sum(w[j] * z[j] for j in range(dim))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, dot))))
            r = y - p
            gb += r
            for j in range(dim):
                gw[j] += r * z[j]
        for j in range(dim):
            w[j] += lr * (gw[j] - l2 * w[j])
        b += lr * gb

    # undo standardization, clip, normalise
    raw = [max(w[j] / sds[j], 0.0) for j in range(dim)]
    total = sum(raw)
    return [r / total for r in raw] if total else [1.0 / dim] * dim


def cllr_report(target: list[float], nontarget: list[float], folds: int = 2) -> dict:
    """Full calibration report: cllr (cross-validated logistic), cllr_min (PAV), cllr_cal.

    The logistic model is fit on held-out folds so `cllr` measures calibration that
    generalizes, not a model that has already seen the trial it is scoring.
    """
    if len(target) < folds * 2 or len(nontarget) < folds * 2:
        return {"cllr": float("nan"), "cllr_min": float("nan"), "cllr_cal": float("nan")}

    tar_llr: list[float] = []
    non_llr: list[float] = []
    for f in range(folds):
        tr_t = [s for i, s in enumerate(target) if i % folds != f]
        tr_n = [s for i, s in enumerate(nontarget) if i % folds != f]
        te_t = [s for i, s in enumerate(target) if i % folds == f]
        te_n = [s for i, s in enumerate(nontarget) if i % folds == f]
        # the len >= folds*2 guard above puts at least two trials of each class in
        # both halves of every fold, so no split can lose a class here
        model = fit_logistic(tr_t + tr_n, [1] * len(tr_t) + [0] * len(tr_n))
        tar_llr += calibrate_llr(model, te_t, len(tr_t), len(tr_n))
        non_llr += calibrate_llr(model, te_n, len(tr_t), len(tr_n))

    actual = cllr(tar_llr, non_llr)
    floor = min_cllr(target, nontarget)
    return {
        "cllr": round(actual, 4) if actual == actual else actual,
        "cllr_min": round(floor, 4) if floor == floor else floor,
        "cllr_cal": round(actual - floor, 4) if actual == actual and floor == floor else float("nan"),
    }
