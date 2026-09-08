"""voicemetric — measure how alike two pieces of writing are, and say how sure you are.

Standalone by construction: this package imports nothing from the rest of revoice. Its
whole dependency surface is the Python standard library. Give it text, get back numbers.

    from revoice.voicemetric import baseline_from_texts, score_text

    baseline = baseline_from_texts(list_of_reference_documents)
    result = score_text(candidate, baseline)
    result["composite"]        # 0-100
    result["components"]       # per feature-family similarity

    from revoice.voicemetric import Population, VoiceRegion, similarity_report

    pop = Population.fit(background_corpus)            # what "typical" means here
    voice = VoiceRegion.fit("manu", my_documents, pop) # a region, not a point
    report = similarity_report(candidate, voice, pop)  # + bootstrap interval, per axis

Three layers, each usable on its own:

  features    deterministic stylometry — function words, n-grams, rhythm, punctuation,
              length-stable vocabulary richness (Yule's K, MTLD)
  baseline    corpus baselines and the composite score, with span-length calibration
  space       the same writing as 17 NAMED axes you can read, plot and argue with,
              plus bootstrap confidence intervals and an SVG report

  verify      the honest scoring of any of it: AUC, EER, PAV, Cllr, weight fitting
  bench       an authorship-verification harness — work-level leave-one-out, hard
              negatives, per-genre breakdown. This is what stops the rest being vibes.

Two commitments the code keeps:

  * **No LLM anywhere.** Every number here is deterministic given its inputs.
  * **No number without its uncertainty** where one can be had. A point estimate that
    hides a 14-point confidence interval is worse than no estimate, because it invites
    a decision the measurement cannot support.

What it is honestly good at: noticing that an edit moved a document's register. What it
is not: authorship attribution. Measured across 70 authors in 11 genres with same-genre
negatives, the composite reaches AUC ~0.69. See docs/metrics.md for the evidence and
the limits, and README.md here for the shape of the API.
"""

import hashlib
import json

from revoice.voicemetric.baseline import (
    COMPONENTS,
    MIN_WORDS_RELIABLE,
    SPAN_BUCKETS,
    VOICE_COMPONENTS,
    WEIGHTS,
    baseline_from_texts,
    calibration_from_texts,
    score_text,
    span_floor,
)
from revoice.voicemetric.features import fingerprint, tokenize
from revoice.voicemetric.space import (
    AXES,
    AXIS_NAMES,
    Population,
    VoiceRegion,
    coordinates,
    effective_dimensionality,
    similarity_report,
)
from revoice.voicemetric.verify import auc, cllr, cllr_report, eer, fit_weights, tpr_at_fpr

# Pre-1.0 deliberately, and it matters. The scoring CONFIGURATION is still moving —
# the composite weights have been refitted three times and the feature set has changed
# — so scores from different MINOR versions are not comparable. That is exactly what
# `signature()` exists to make visible rather than silent.
#
#   MAJOR  the API changes
#   MINOR  the numbers change (weights, features, calibration)
#   PATCH  neither
__version__ = "0.4.0"


def version() -> str:
    """The engine version, for recording alongside anything it measured."""
    return __version__


def signature() -> str:
    """Short stable hash over everything that changes a score.

    The version says which release; this says whether two results are comparable. It
    covers the components and their weights, the named axes, and the span-calibration
    buckets — change any of them and previously stored baselines, calibrations and
    scores are measuring something subtly different. Refitting the weights (which has
    happened three times) moves this without touching a line of API.
    """
    payload = json.dumps({
        "components": list(COMPONENTS),
        "weights": {k: round(float(v), 6) for k, v in sorted(WEIGHTS.items())},
        "voice_components": list(VOICE_COMPONENTS),
        "axes": list(AXIS_NAMES),
        "span_buckets": [list(b) for b in SPAN_BUCKETS],
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def describe() -> dict:
    """Everything a caller should record to make a measurement reproducible."""
    return {
        "name": "voicemetric",
        "version": __version__,
        "signature": signature(),
        "components": list(COMPONENTS),
        "weights": dict(WEIGHTS),
        "axes": list(AXIS_NAMES),
        "llm": False,
    }


__all__ = [
    "AXES", "AXIS_NAMES", "COMPONENTS", "MIN_WORDS_RELIABLE", "Population",
    "VOICE_COMPONENTS", "VoiceRegion", "WEIGHTS", "auc", "baseline_from_texts",
    "calibration_from_texts", "cllr", "cllr_report", "coordinates",
    "effective_dimensionality", "eer", "fingerprint", "fit_weights", "score_text",
    "similarity_report", "span_floor", "tokenize", "tpr_at_fpr",
    "SPAN_BUCKETS", "describe", "signature", "version",
]
