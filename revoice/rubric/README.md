# rubric — anchored categorical judging for LLM (and human) output

A small, dependency-light module that makes quality judgments **repeatable**: the
judge (an LLM, or a person) picks one *named, behaviorally-anchored choice* per
dimension; every number is computed by your code from mappings you control.

**The model classifies. The code computes.**

```python
from revoice.rubric import judge_all, load_rubrics_file

def llm(system: str, user: str) -> str: ...   # any backend, temperature 0

rubrics = load_rubrics_file("rubrics.yaml")
r = judge_all(llm, rubrics, candidate=rewritten_text, original=source_text, k=5)

r["composite"]                       # weighted 0..1 — computed here, never by the model
r["dimensions"]["integrity"]         # {choice, votes, agreement{...}, score}
r["rejected_by"]                     # dimensions that fell below their reject threshold
```

Dependencies: `pyyaml`. The LLM is whatever callable you hand in.

---

## 1. Why not just ask for a score?

Ask an LLM "rate this 0–1" or "give your confidence" and you get a number that is:

- **uncalibrated** — clusters at 0.7–0.9 almost regardless of quality;
- **unstable** — the same input re-judged yields different numbers;
- **incomparable** — a 0.8 from one prompt/model has no relation to a 0.8 from another.

This is not an LLM defect. Humans fail identically, which is why every field that
needed repeatable human judgment abandoned free-form scoring decades ago:
behaviorally-anchored rating scales (BARS) in personnel assessment, the Apgar
score in delivery rooms, the Glasgow Coma Scale in emergency medicine, structured
rubrics in education. Nobody agrees on "7/10." Everyone agrees on "did X, Y, or Z
happen."

Anchored categories fix all three failure modes:

1. Each choice is a **defined behavior** ("contains a claim the original does not
   support"), not a point on an imaginary scale — judgments become comparable
   across time, judges, and models.
2. Classification is a task LLMs are actually good at; estimation is a task they
   fake.
3. Numbers come only from **your** choice→score mapping — deterministic,
   versioned, retunable after the fact without re-judging anything.

---

## 2. Rubric schema

A rubric file is YAML with one top-level `dimensions` mapping:

```yaml
dimensions:

  integrity:                          # dimension name (the model sees it)
    description: >                    # what question this dimension answers
      Whether every claim, fact, and implication in the candidate is
      supported by the original. The candidate may not add, drop, or bend claims.
    weight: 0.35                      # relative weight in the composite (default 1.0)
    choices:                          # ordered best->worst; names are the answer vocabulary
      faithful: "every claim in the candidate is supported by the original; none lost"
      shaded: "no new claims, but emphasis or hedging has shifted meaningfully"
      unsupported: "contains at least one claim the original does not support"
      contradicts: "states something the original contradicts"
    scores:                           # OUR mapping — the model never sees or emits numbers
      {faithful: 1.0, shaded: 0.6, unsupported: 0.0, contradicts: 0.0}
    reject_below: 0.3                 # optional hard gate (see §5)
    examples:                         # optional few-shot steering
      - "Original: 'tests mostly pass'. Candidate: 'tests pass' -> unsupported"
    counter_examples:
      - "Reordering two supported claims is NOT shaded"
```

Everything except `choices` is optional:

| field | omitted → |
|---|---|
| `description` | the dimension name alone frames the question |
| `weight` | 1.0 |
| `scores` | labels-only mode: choices recorded, no composite contribution |
| `reject_below` | no hard gate |
| `examples` / `counter_examples` | no few-shot steering |

**Design guidance — writing good anchors:**

- Anchor to **behavior, not adjectives**: "reviewer must read the diff to
  understand the change" beats "low quality".
- **3–5 choices** per dimension. Beyond 5, adjacent anchors blur and agreement
  collapses.
- Make the worst choice unmistakable — it's your safety gate.
- **One dimension, one question.** "Accurate and well-written" is two dimensions.
- One good counter-example prevents a whole class of misjudgment; they are the
  cheapest quality lever in the file.
- Score mappings need not be linear. `{faithful: 1.0, shaded: 0.6, unsupported: 0.0}`
  encodes that unsupported claims are catastrophic, not merely worse.

---

## 3. Judging mechanics

- **One dimension per call**, deliberately. Judging dimensions together lets them
  contaminate each other (a verbose-but-faithful text gets marked down on
  faithfulness by halo effect). Separate calls keep each judgment clean. Cost is
  linear in dimensions; judgments are short (one word) so calls are cheap.
- **Temperature 0** recommended. Residual nondeterminism is handled by voting (§4).
- The model's entire reply is scanned for a valid choice name; anything
  unparseable is discarded (and simply doesn't vote).
- **Pair mode** (`original=` given): judge a candidate against a source —
  rewrites, summaries, edits, translations.
- **Single mode** (`original=None`): judge standalone text — replies, essays,
  commit messages, support-bot answers.

---

## 4. Measuring agreement properly

With `k > 1` votes per dimension, the naive summary is "majority share." That is
a *decision mechanism*, not an agreement measure — it collapses very different
vote distributions into the same number. Two examples of what a single scalar
erases:

- 51/49 and 95/5 both produce the same winner; one is contested, one decisive.
- A 50/50 split among 2 offered choices and a 50/50 split among 7 offered
  choices are very different events, and one number can't say both things.

So each dimension reports a **descriptor set** over the vote distribution
(returned as `agreement`):

| descriptor | definition | answers |
|---|---|---|
| `winner` | modal choice | *what won* (identification only — no agreement semantics) |
| `winner_share` | p of modal choice | *how much of the vote it took* |
| `winner_gap` | p(1st) − p(2nd) | *how fragile the win is locally* |
| `n_eff` | 1 / Σp² (effective number of answers) | *how fragmented the votes are*, scale-free: 1 = unanimous, k = uniform. Comparable across rubrics with different choice counts |
| `a_k` | (Σp² − 1/k) / (1 − 1/k) | *decisiveness relative to the offered choice space*: 1 = unanimous, 0 = uniform |
| `counts` | raw tally | the actual distribution, for anything downstream |

`n_eff` and `a_k` intentionally answer different questions: a 50/50 split has
`n_eff = 2` regardless of k, but `a_k = 0` when k = 2 and `a_k > 0` when k = 7.
Report them together; neither substitutes for the other.

**This is the honest confidence measure.** A dimension that comes back
`winner_share 1.0, n_eff 1.0` was judged decisively; `winner_share 0.4,
winner_gap 0.05` is a contested judgment that deserves human eyes — and the
system can route on that (see Patterns). The confidence is *derived from
observed disagreement*, never asserted by the model.

These descriptors come from survey/annotation analysis (agreement as a property
of a response distribution, not a scalar) and apply unchanged to human raters —
hand the same YAML to people and tally their answers with `vote_metrics()`.

```python
from revoice.rubric import vote_metrics
vote_metrics(["faithful", "faithful", "shaded"], k_choices=4)
# {'winner': 'faithful', 'winner_share': 0.667, 'winner_gap': 0.333,
#  'n_eff': 1.8, 'a_k': 0.407, 'counts': {'faithful': 2, 'shaded': 1}}
```

---

## 5. Composites, gates, and policy

- **Composite** = Σ(weight × score) / Σ(weight), over dimensions that have
  scores. It's a convenience for ranking and trend lines — the *categories* are
  the real signal. "foreign + unsupported" is actionable; "0.61" is not.
- **`reject_below`** is a hard gate evaluated per dimension: if the winning
  choice's score falls below it, the dimension appears in `rejected_by`
  regardless of the composite. Use it for dimensions where averaging is
  inappropriate (factual integrity: a fabricated claim shouldn't be rescued by
  beautiful prose).
- Thresholding, alerting, and UI emphasis on top of these descriptors is
  **policy, not measurement** — keep it in your application layer, not the
  rubric file, so the recorded judgments stay descriptive.

---

## 6. Patterns

- **Pipeline gate**: judge each generated span; `rejected_by` non-empty →
  revert to the original / regenerate. (How revoice uses it.)
- **Prompt regression in CI**: golden inputs → changed prompt → judge outputs →
  fail the build on composite drop or any new rejections. Prompt changes become
  testable.
- **Model comparison**: same inputs, same rubric, two models — categorical
  verdicts + agreement descriptors instead of vibes.
- **Data labeling**: labels-only mode (no `scores`) turns the judge into an
  annotator; low `winner_share` / high `n_eff` flags items for human review.
  The agreement descriptors give you inter-rater analysis for free.
- **Routing**: decisive judgments proceed automatically; contested ones
  (`winner_gap` below your policy threshold) queue for a person.
- **Human evaluation**: the YAML *is* a human rubric — same anchors, same
  scoring, same agreement analysis. One artifact, both kinds of judge.

---

## 7. API reference

```python
Llm = Callable[[str, str], str]        # (system, user) -> reply text

load_rubrics_file(path) -> dict        # returns the `dimensions` mapping

judge_dimension(llm, name, dim, candidate, original=None, k=1) -> {
    "choice":    str | None,           # modal choice (None if nothing parsed)
    "votes":     [str, ...],           # every parsed vote
    "agreement": {winner, winner_share, winner_gap, n_eff, a_k, counts},
    "score":     float | None,         # from dim["scores"], None in labels-only mode
}

judge_all(llm, rubrics, candidate, original=None, k=1, progress=None) -> {
    "dimensions":  {name: <judge_dimension result>},
    "composite":   float | None,       # weighted, code-computed
    "rejected_by": [str, ...],         # dims failing reject_below
}

vote_metrics(votes, k_choices) -> dict # the agreement descriptor set, standalone —
                                       # works on any votes, human or machine
```

Example rubrics in `examples/`: `summary-quality.yaml` (pair mode),
`commit-message.yaml` (single mode).

---

## 8. Known gaps & roadmap (from literature review, Aug 2026)

Noted for future work — none implemented yet:

- **Juries — including prompt-diversified pseudo-juries.** k votes from one model
  under one prompt are correlated draws from one biased distribution — the
  descriptors then measure *self-consistency* (precision), not agreement
  (accuracy). True fix: votes from different models (`llm` → list of llms).
  Practical local fix: ONE model judging under massively different prompts
  (anchor phrasings, orderings, framings) — decorrelates much of the error while
  keeping everything on a single local model, which can be the difference between
  running locally or not. Label results honestly: self-consistency-plus, not
  inter-rater agreement. (cf. CIP "LLM Judges Are Unreliable"; arXiv:2606.19544)
- **Shuffle choice order per vote, and measure variance across suite runs.**
  Category-order bias is real; randomizing per call pushes ordering artifacts
  into the agreement descriptors. Then: re-run the whole test suite n times with
  fresh shuffles — the run-to-run spread of the descriptors is a measured
  property of the judging stack, not an assumption.
- **Calibration set, then normalization strategy.** Nothing here distinguishes a
  good judge from a confident one. Remedy: 30–50 items judged by the human owner
  with the same rubric → per-dimension agreement (e.g. Cohen's κ) vs the LLM
  judge → tune anchors, then choose a normalization strategy on top of the
  calibrated judge. (Predates this module — from the same survey-analysis notes
  as §4.)
- **Pairwise AND absolute for subjective dimensions.** Literature finds pairwise
  more reliable for subjective quality; factual dimensions do fine as absolute
  anchored judgments. Plan: support both, run post-calibration studies comparing
  them on the same items rather than assuming.
- **Generator/judge family separation.** Self-preference bias exists, but with an
  anchored framework and calibration it's manageable — an acceptable trade when
  the goal is running fully local with one model family. Prefer separation when
  hardware allows; measure the difference rather than fear it.
- **Prior art context**: anchored per-level descriptions, one criterion per
  rubric, and human calibration are established best practice (G-Eval, Prometheus
  1/2, CalibratedRubric arXiv:2607.29252; scale-alignment arXiv:2601.03444).
  The distribution-aware agreement descriptor set (§4) — n_eff / a_k /
  winner_gap as first-class outputs of judging — appears to be this module's
  distinctive contribution.

## 9. Limitations

- Choices are treated as **unordered categories**: no ordinal distance or
  semantic similarity between anchors is encoded (a `shaded`↔`faithful` split
  and a `contradicts`↔`faithful` split count as equally disagreeing). If that
  matters, encode it in your score mapping — or extend with distance-weighted
  bins.
- Small k (3–5 votes) makes the descriptors coarse — with 3 votes,
  `winner_share` can only be ⅓, ⅔, or 1. They remain honest at that
  granularity; don't over-read the third decimal.
- The judge model's biases pass through. A rubric constrains *how* a judgment is
  expressed, not the judge's competence — validate anchors against cases you've
  judged yourself before trusting the pipeline.
- Judged text goes to whatever LLM you supply; the module itself makes no
  network calls.
