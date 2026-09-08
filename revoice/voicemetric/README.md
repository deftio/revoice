# voicemetric

Measure how alike two pieces of writing are — and say how sure you are.

Standalone by construction: **nothing here imports from the rest of revoice**, and the
entire dependency surface is the Python standard library. Give it text, get numbers.
revoice is one caller; the package does not know that.

Sibling of [`revoice/rubric/`](../rubric/README.md), which does the same for *judging*
what a model wrote. Same division of labour: the generic engine here, the
voice-pack-aware wrappers in `revoice/core/metrics.py`.

**Version:** `voicemetric.version()` → `0.4.0`  ·  `voicemetric.signature()` → a short
hash over everything that changes a score. Record both with any result. See
[Versioning](#versioning) — it is the difference between a comparable number and a
mystery.

---

## The two questions it answers

**"How close is this text to that corpus?"** — a composite score with per-component
breakdown.

```python
from revoice.voicemetric import baseline_from_texts, score_text

baseline = baseline_from_texts(reference_documents)   # list[str]
r = score_text(candidate, baseline)
r["composite"]     # 0-100
r["components"]    # {"delta": 0.61, "ngram": 0.55, "punct": 0.48, ...}
```

**"Where does this sit, and on which axes?"** — coordinates in a named space, with a
confidence interval.

```python
from revoice.voicemetric import Population, VoiceRegion, similarity_report

pop   = Population.fit(background_corpus)              # what "typical" means here
voice = VoiceRegion.fit("manu", my_documents, pop)     # a region, not a point
rep   = similarity_report(candidate, voice, pop)

rep["overall"], rep["low"], rep["high"]   # 45.9, 31.9, 49.1
rep["axes"]["subordination"]              # similarity, interval, signed deviation
voice.deviations(candidate, pop)[:3]      # the axes that differ most, largest first
```

The second is usually the more useful. A composite says *72*; a region says *your
sentences run 1.8 sd long and you are using half your usual semicolons*.

---

## Layout

| module | what it is |
|---|---|
| `features.py` | deterministic stylometry: function words, char/word n-grams, sentence and paragraph shape, punctuation habits, length-stable vocabulary richness (Yule's K, MTLD) |
| `baseline.py` | corpus baselines, the composite score, span-length calibration |
| `space.py` | 17 named axes, voice regions, bootstrap intervals, effective dimensionality |
| `chart.py` | the report as dependency-free SVG |
| `verify.py` | AUC, EER, `tpr_at_fpr`, PAV isotonic regression, Cllr, weight fitting |
| `bench.py` | authorship-verification harness: work-level LOO, hard negatives, per-genre breakdown, `--fit` |

`verify` and `bench` are the point of the other four. Without them the rest is vibes
with decimal places.

---

## Two commitments

**No LLM anywhere.** Every number is deterministic given its inputs and a seed.

**No number without its uncertainty**, wherever one can be had. A point estimate that
hides a 14-point confidence interval is worse than no estimate, because it invites a
decision the measurement cannot support. Where a text is too short to bootstrap, the
report says so rather than drawing a band it cannot justify.

---

## What it is honestly good at

Noticing that an edit moved a document's **register** — that a passage was rewritten
into machine-flavoured or institutional prose, that a draft drifted away from how the
rest of the document reads.

**It is not an authorship test.** Measured across 70 authors in 11 genres with
same-genre negatives (different author, same era and genre — the contrast that
matters), the composite reaches **AUC ≈ 0.69** and Cllr ≈ 0.94, where 1.0 is a system
carrying no information at all. Difficulty varies by genre: 0.69 telling comic writers
apart, 0.67 on technical prose, 0.55 on academic philosophy.

Read those numbers as the ceiling, not the floor. Anyone reaching for this to decide
*who wrote something* should read [`docs/metrics.md`](../../docs/metrics.md) first,
which records the evidence, the failure modes, and the things that turned out to be
measuring topic rather than voice.

---

## Benchmarking

```bash
revoice bench bench-corpus --hard-negatives --fit   # AUC/Cllr by length, fitted weights
revoice space bench-corpus -c bench-corpus-registers # the axes, and where groups sit
```

The corpora are built by `scripts/fetch_bench_corpus.py` (70 authors, 11 genres) and
`scripts/fetch_register_corpus.py` (140 modern documents, 5 registers), both from
public-domain and openly licensed sources.

Weights are **fitted on held-out reference models**, never hand-picked — an earlier
hand-picked set lost to plain equal weighting, and a set fitted on one genre lost to
equal weighting on all eleven.

---

## Install, build, test

Today it ships inside revoice and needs no build step — pure Python, standard library
only, no compiled parts:

```bash
pip install revoice            # or, from a checkout:
uv sync --all-extras           # exact pinned environment
python -c "import revoice.voicemetric as vm; print(vm.version(), vm.signature())"
```

Run its tests on their own:

```bash
pytest tests/test_voicespace.py tests/test_bench.py tests/test_verify.py \
       tests/test_stylometry.py tests/test_package_boundaries.py -q
```

`test_package_boundaries.py` is the one that keeps this package standalone: it parses
the AST of every source file and fails if any of them imports from the rest of revoice
or picks up a third-party dependency — including imports hidden inside function bodies,
which is how that kind of coupling normally arrives.

Lint and the coverage gate are the project's, and this package is held to them:

```bash
ruff check revoice/voicemetric/
pytest tests/ -q --cov=revoice --cov-fail-under=100
```

## Versioning

Two numbers, because they answer different questions.

```python
import revoice.voicemetric as voicemetric

voicemetric.version()     # "0.4.0"        which release
voicemetric.signature()   # "bfd1b0992fc8" whether two results are comparable
voicemetric.describe()    # both, plus components, weights and axes — JSON-safe
```

**Why a signature as well as a version.** The composite weights have been refitted three
times, each time changing every score computed against an existing baseline, and none of
those refits touched a single function signature. A release number would have said
nothing. `signature()` hashes the things that actually move numbers — the components and
their weights, the named axes, the span-calibration buckets — so a changed score is a
visible diff rather than a puzzle.

Semantics, deliberately pre-1.0:

| bump | means |
|---|---|
| MAJOR | the API changed |
| MINOR | **the numbers changed** — weights, features, calibration |
| PATCH | neither |

**What revoice does with it.** `learn` stamps `describe()` into `params/baselines.json`,
`params/calibration.json` and the pack manifest. `revoice status <voice>` then warns when
a pack's baselines were built under a different signature, because its stored bands are
measuring something subtly different from anything you compute today:

```
warning: baselines were built by voicemetric 0.3.0 (signature 0000deadbeef);
         this build is 0.4.0 (signature bfd1b0992fc8).
         scores are not comparable across signatures — rerun: revoice learn twain
```

`revoice doctor` prints both engines' versions and signatures.

---

## If this ever leaves the repo

It is already shaped for it. The seam is `revoice/core/metrics.py` — read a pack's
corpus, hand texts here, write results back — plus the `read` callable that
`bench.load_corpus` takes so this package never learns what a `.docx` is. Nothing else
crosses.
