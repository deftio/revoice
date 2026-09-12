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

## The three questions it answers

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

**"Did this rewrite move toward that voice, and did it keep the meaning?"** — the paired
question, and the one worth trusting most.

```python
from revoice.voicemetric import grade

g = grade(source, rewrite, voice, pop)

g["style"]["delta"]      # +11.4  — signed movement toward the voice
g["style"]["low"], g["style"]["high"]   # the interval on the MOVEMENT, not the level
g["style"]["moved"]      # True only if that interval clears zero
g["meaning"]["families"] # {"numbers": 1.0, "negation": 0.5, "content": 0.94, ...}
g["verdict"]             # "meaning drift — negation preserved at 0.50"
```

The second is usually more useful than the first: a composite says *72*; a region says
*your sentences run 1.8 sd long and you are using half your usual semicolons*.

The third is the one to reach for when you can. The first two ask an **absolute**
question — *is this text by X?* — and answer it weakly, at AUC ≈ 0.69. The third asks a
**paired** one: source and rewrite share their topic, genre, length and content, so
every confound that makes the absolute question hard sits on both sides of the
subtraction and cancels. The same features support a much stronger claim on a difference
than on a level.

Two things it will not do. `moved` is false unless the whole confidence interval clears
zero — a delta of +9 with an interval of [−4, +21] is reported as *no measurable
movement*. And the meaning axis **vetoes**: a rewrite that moved 14 points toward the
voice while dropping a third of the source's figures is a failure, not a partial success,
so `grade()` returns both axes and refuses to average them.

---

## Layout

| module | what it is |
|---|---|
| `features.py` | deterministic stylometry: function words, char/word n-grams, sentence and paragraph shape, punctuation habits, vocabulary richness that is steadier in length than TTR (Yule's K, MTLD — steadier, not flat: see §1g) |
| `baseline.py` | corpus baselines, the composite score, span-length calibration |
| `space.py` | 17 named axes, voice regions, bootstrap intervals, effective dimensionality |
| `chart.py` | the report as dependency-free SVG |
| `transfer.py` | grading a **rewrite**: signed movement toward a voice with an interval, and whether the meaning survived it |
| `verify.py` | AUC, EER, `tpr_at_fpr`, PAV isotonic regression, Cllr, c@1, weight fitting |
| `bench.py` | authorship-verification harness: work-level LOO, hard negatives, per-genre breakdown, length sensitivity, `--fit` |

`verify` and `bench` are the point of the other four. Without them the rest is vibes
with decimal places.

---

## Three commitments

**No LLM anywhere.** Every number is deterministic given its inputs and a seed.

**No number without its uncertainty**, wherever one can be had. A point estimate that
hides a 14-point confidence interval is worse than no estimate, because it invites a
decision the measurement cannot support. Where a text is too short to bootstrap, the
report says so rather than drawing a band it cannot justify.

A third, which is a constraint rather than a principle: **it has to run in a browser.**
The compare page is served off GitHub Pages with no server to ask, so everything here is
stdlib Python written to port one-to-one into `pages/voicespace.js`. That rules out
sklearn, spaCy and every embedding model, and `tests/test_package_boundaries.py` enforces
the Python half by AST-parsing the package for forbidden imports while
`tests/test_pages_parity.py` runs the JavaScript under node against this code on shared
fixtures. `transfer.py` goes further and implements the *browser's* LCG for its
bootstrap, because a delta's verdict turns on whether its interval excludes zero and an
approximate match would let page and tool disagree about whether a rewrite worked.

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

Read those numbers as the ceiling, not the floor — and note that they are the ceiling on
the *absolute* question. `transfer.grade` asks the paired one, where those confounds
cancel; that is the number to prefer whenever you have a before and an after.

Anyone reaching for this to decide *who wrote something* should read
[`docs/metrics.md`](../../docs/metrics.md) first, which records the evidence, the failure
modes, and the things that turned out to be measuring topic rather than voice — including
§1g, where the diagnostic found two axes running dead in the bench and corrected a
length-independence claim this package had made about itself without a source.

---

## Benchmarking

```bash
revoice bench bench-corpus --hard-negatives --fit    # AUC/Cllr/c@1 by length, fitted weights
revoice space bench-corpus -c bench-corpus-registers # the axes, and where groups sit
revoice rewrite-score draft.md revised.md --against twain   # the paired question
```

Every bench cell also reports `decision`: **c@1** (Peñas & Rodrigo 2011, the PAN
verification measure), the abstention band that scored best, and the abstention rate it
bought. AUC and EER grade a ranker; this engine has to decide, and its most common
correct answer is "these overlap, I cannot call it" — c@1 is the only measure here that
can score that as anything but a coin flip.

```python
from revoice.voicemetric.bench import length_sensitivity, render_length_sensitivity
print(render_length_sensitivity(length_sensitivity(docs, cut="words")))
```

Truncates each document to every length in the grid and reports how far each axis moves
when *only the amount of text* changed. It exists because `yules_k` once asserted, with
no source, that Yule's K does not drift with length (Tweedie & Baayen 1998 found no
member of that family constant). On its first run it also found that `bench._window`
joins a span's words on spaces, leaving one paragraph — so the two paragraph-shape axes
are pure length readings inside the bench, while being perfectly fine on the page, where
windows are cut on paragraph boundaries. Hence the two `cut` modes.

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
       tests/test_transfer.py tests/test_stylometry.py \
       tests/test_package_boundaries.py tests/test_pages_parity.py -q
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

voicemetric.version()     # "0.5.0"        which release
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
| MAJOR | the API changed in a way that breaks a caller |
| MINOR | **the numbers changed** — weights, features, calibration — or the API grew |
| PATCH | neither |

0.5.0 is the first release where the version moved and the signature did not: it added
`transfer` and `c_at_1` without shifting a single existing number, so scores from 0.4.0
and 0.5.0 remain comparable. That is exactly the distinction the signature exists to
draw.

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
