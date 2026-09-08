# Voice metrics — design & validation plan

> Status: §1-§4 are implemented and measured (`revoice bench`); §3 Space 1 and §5-§6 are
> the plan. Supersedes the "Voice-match metrics" section of [architecture.md](architecture.md),
> which describes what is *implemented*, not what is *validated*.

**The thesis of this document:** revoice's central claim — "text already in your voice passes
through byte-identical; text that isn't gets rewritten" — is a *classifier decision*. Every other
part of the system (minimal-touch, register attribution, the review flywheel's labels, any
comparison between a prompted baseline and a fine-tuned model) depends on that classifier being
right. Until September 2026 we had never measured whether it is. `revoice bench` now measures
it, this document records what that measurement says, and §3-§6 are the design and plan that
follow.

**The headline:** under a topic-controlled protocol the shipped composite scores AUC 0.650
and Cllr 0.941 — where 1.0 is the system that always answers "don't know" — and at a 5%
false-positive rate it keeps 14% of the author's own text untouched. The metric is not yet
fit for the decision the pipeline makes with it. What follows is the evidence and the fix.

**Constraint accepted up front:** the bench must run with **no LLM**. Voice measurement is
deterministic or learned-but-frozen; the LLM-judge rubrics (`revoice/rubric/`) are a *separate*
instrument answering a different question, and they stay optional. Nothing in this document
requires a model that generates text.

---

## 1. What we measured (September 2026)

All numbers below come from the bundled example packs (Twain, 20 docs; Darwin, 22 docs), using
leave-one-out baselines (hold out a document, rebuild the baseline from the rest, score sampled
word-windows from the held-out document) with ground-truth register labels recovered from the
example corpora's filenames (`essay-*` / `fiction-*`, `memoir-*` / `science-*`).

### 1.1 Minimal-touch is misfiring

Scoring real Twain paragraphs against Twain's own baseline, with the pipeline's own threshold
(`on_target_floor = self_mean - self_std`, see `core/pipeline.py`):

```
twain/professional floor = 54.6   (self_mean 57.9, self_std 3.3)

TWAIN  spans vs twain baseline:  n=38   mean 49.0   below floor  30/38  (79%)
DARWIN spans vs twain baseline:  n=210  mean 41.9   below floor 209/210
```

**79% of genuine Twain paragraphs are classified "rewrite."** The cause is a units mismatch:
`calibration.json` is built by scoring whole *documents*, but the floor is applied to *spans*.
The composite is strongly length-dependent, so a band centred on 57.9 (per-document) is simply
the wrong ruler for a 90-word paragraph. Span-level AUC (Twain vs Darwin, Twain baseline) measured
0.80 under document-level leave-one-out — but that protocol leaks topic, and under the
bench's work-level control the composite is 0.650 (§1.2). Re-calibrating the threshold
is necessary but nowhere near sufficient.

### 1.2 The composite is beaten by its own best component

Reproduce with `revoice bench examples/voices` (defaults: work-level LOO, 40 queries per
cell, seed 17). AUC by query length:

```
scorer                       50w    100w    200w    400w    macro
vocab                      0.745   0.782   0.833   0.793    0.788
ngram                      0.653   0.659   0.706   0.727    0.686
composite  (shipped)       0.617   0.602   0.653   0.727    0.650
no-vocab                   0.609   0.590   0.637   0.718    0.639
delta+ngram                0.616   0.595   0.628   0.649    0.622
shape                      0.567   0.579   0.599   0.689    0.608
rhythm                     0.563   0.549   0.601   0.663    0.594
delta                      0.580   0.553   0.578   0.608    0.580
punct                      0.470   0.497   0.569   0.771    0.577
```

1. **`vocab` (tf-idf) beats the whole composite** — 0.788 vs 0.650. And per §1.3 it is
   the component that collapses hardest under topic control, so the one thing carrying
   the composite is the one thing measuring subject matter.
2. **The hand-picked weights destroy signal.** The composite loses to `ngram` alone at
   every length. Nobody ever fit these weights to data.
3. **Half the components are near chance**: `delta` 0.580, `rhythm` 0.594, `punct` 0.577.
   Together they carry weight 0.50.
4. **`punct` is anti-predictive on short spans** (0.470 at 50w) and then jumps to 0.771 at
   400w — behaviour that unstable is not a feature, it is a length artefact.

### 1.3 Most of the apparent performance is topic, not voice

The bench runs the same trials twice: once where the reference model cannot see the work
the query came from (topic controlled) and once where it can (topic leaks). The gap is
the share of performance that was subject matter:

```
scorer                  controlled   leaked   topic share
vocab                        0.788    0.950         0.162
punct                        0.577    0.702         0.126
composite                    0.650    0.773         0.124
ngram                        0.686    0.798         0.112
delta                        0.580    0.682         0.102
rhythm                       0.594    0.649         0.055
```

Under the leaky protocol the composite looks like a 0.773 measure. Under topic control
it is 0.650. **Every previously reported figure for this metric — including the demo
site — was measured the leaky way.** Twain's essays are about lying and his fiction
about Adam and a dog; Darwin's science is about species and his memoir about his life.
Document-level leave-one-out leaves the query's subject sitting in its own reference.

### 1.4 The browser demo measured worse than the local tool — and was fixed by the bench

The GitHub Pages demo runs a four-component JavaScript subset (no tf-idf, no scalar
shape). Its weights were hand-picked at `delta .3 / ngram .3 / rhythm .2 / punct .2`.
Run through the same bench:

```
weighting                            50w    100w    200w    400w   macro     EER
ngram .6 delta .2 rhythm .1 punct .1  0.657  0.643  0.693  0.756   0.687   0.367
ngram only                            0.653  0.659  0.706  0.727   0.686   0.358
current browser .3/.3/.2/.2           0.608  0.578  0.638  0.739   0.641   0.401
```

The pages now ship the bench-selected blend. Character n-grams carry nearly all of the
real signal; the other three are kept at low weight because they make the on-page
component breakdown diagnostic, not because they discriminate. `pages/stylometry.js` and
`scripts/export_demo_baselines.py` must keep these weights in sync — the exporter mirrors
the JS scorer so the demo's calibration bands match what the browser computes.

Two related fixes landed with it: both the JS `buildBaseline()` and the Python exporter
now self-calibrate **leave-one-out** (a window scored against a baseline it helped build
pulls the mean toward itself — Twain/fiction's self-band moved 59.4 → 55.3 once corrected),
and the pages report a **z-score against the reference's own variation** rather than a
percentage of it, because a ratio of two numbers that both sit near 55 saturates.

### 1.5 What the browser metric actually measures: register, not authorship

The most useful thing the bench surfaced is not a number but a diagnosis. With Twain's
*A Dog's Tale* as the reference:

```
same author, same work (topic leaks)  +4.5σ   no drift
DIFFERENT AUTHOR (Darwin, memoir)     +2.5σ   no drift      <-- wrong, and stubborn
same author, different work (diary)   -5.4σ   clear drift   <-- also wrong
same author, essay                    -3.9σ   clear drift
AI-flavoured prose                    -7.8σ   clear drift
```

Better weights did not fix this and cannot: Twain's first-person narrative is genuinely
closer in surface form to Darwin's first-person memoir than to Twain's own comic diary.
Sub-word texture, function-word rates, sentence rhythm and punctuation track **how a
passage is pitched** far more than **who wrote it**.

That is a real limit, not a bug to weight away, and it cuts both ways: it is why the
measure is poor at authorship *and* why it is decent at its actual job — noticing that an
edit moved the register (AI-flavoured prose is the most clearly separated case above).
The demo and compare pages now say this in the first screen rather than in a footnote,
report the margin to the runner-up so a 2-point "win" cannot read as a result, and label
the samples that are training data as training data.

### 1.6 The numbers do not mean anything yet

Calibration, macro-averaged over lengths:

```
scorer                    cllr  cllr_min  cllr_cal     eer  tpr@5%fpr
composite                0.941     0.843     0.098   0.408      0.135
vocab                    0.794     0.724     0.070   0.295      0.448
ngram                    0.922     0.868     0.054   0.358      0.118
```

Cllr of 1.0 is the system that always answers "don't know". **The shipped composite
scores 0.941** — as delivered it carries almost no information, and even after ideal
calibration (`cllr_min` 0.843) the discrimination floor is barely below useless.

And the number that matters most: **at a 5% false-positive rate, the composite keeps 14%
of the author's own text untouched.** That is the direct measurement of the minimal-touch
failure in §1.1, and it is the number to move.

### 1.7 Classical stylometry is out of regime here

We tested the two most obvious fixes from the literature (exploratory scripts,
document-level LOO, pre-dating the bench). **Neither worked.**

- **Cosine Delta** (Evert et al. 2017, the best-performing classical Delta variant) scored *worse*
  than the current implementation (0.29–0.68 vs 0.57–0.79) at MFW = 94/300/800.
- **Length-matched reference statistics** (estimating the baseline on windows the same length as
  the query, rather than on full documents) did not help either: 0.497 vs 0.512 at 50w, identical
  at 400w.

The honest reading is not "Cosine Delta is bad." It is that **the entire Delta family is outside
its validated regime at revoice's operating point.** Delta assumes book-length texts and dozens of
reference works to estimate per-word variance. revoice has 25–200-word spans and, for the example
packs, 4–14 reference documents. The literature's commonly cited reliability floor for classical
stylometry is around 1,000 words; revoice operates an order of magnitude below it.

This is the finding that drives the design in §3.

### 1.8 Two outright bugs

- **Contaminated self-calibration.** `metrics.build_baselines()` scores each corpus document
  against a baseline *that includes that document*. The reported `self_mean` band is inflated.
  Fix: leave-one-out.
- **Length-dependent features inside a "shape" score.** `type_token_ratio` and `hapax_ratio` are
  both mathematically length-dependent and both live in `SCALARS`, feeding the `shape` component.
  They are part of why the composite drifts with length.

### 1.9 Coverage is not validation

The suite was 100% line coverage with zero discrimination assertions — `test_stylometry.py`
checks that `cosine(a, a) > 0.999`. Coverage tells us every line ran; nothing told us the
metric works. That gap is what `revoice bench` (§4) now closes.

---

## 1b. What the improvements did (September 2026, second pass)

Everything in §1 was measured on the bundled Twain/Darwin packs, which are confounded
four ways. The work below fixed the units error, replaced the feature set, built a
properly controlled corpus, and fitted the weights instead of guessing them. Three of
the four findings contradict what the confounded corpus had suggested.

### 1b.1 The evaluation corpus, and why it changed the answers

`scripts/fetch_bench_corpus.py` assembles the corpus §4.1 asks for from public-domain
Gutenberg texts: **four 19th-century American humorists — Twain, Bret Harte, Artemus
Ward, Bill Nye — three works each**. Same era, same genre, same register, so telling
them apart is authorship and nothing else. (A matching naturalist group — Darwin,
Wallace, Huxley, Bates — builds the same way.) It is written to a gitignored
`bench-corpus/`: freely re-fetchable, and derived data does not belong in the repo.

Measured on that corpus, with work-level leave-one-out:

```
scorer                       50w    100w    200w    400w    800w    macro
vocab (tf-idf)             0.722   0.739   0.759   0.791   0.808    0.763
equal-weight               0.563   0.585   0.672   0.707   0.718    0.649
delta (Burrows)            0.580   0.569   0.638   0.678   0.710    0.635
punct                      0.540   0.564   0.610   0.663   0.694    0.614
old hand-picked composite  0.510   0.535   0.639   0.649   0.661    0.599
ngram (char 3-gram)        0.507   0.532   0.618   0.619   0.613    0.578
rhythm                     0.547   0.506   0.521   0.496   0.508    0.516
structure                  0.525   0.531   0.481   0.499   0.486    0.505
```

**Character n-grams were measuring topic.** On Twain-vs-Darwin `ngram` was the
strongest component (0.686) and the hand-picked weights leaned on it. Against
same-genre contemporaries it falls to 0.578 — near chance. What it had been reading
was the difference between comic fiction and natural history.

**Burrows' Delta is the best real component** (0.635), which is what a century of
authorship-attribution work would have predicted: it is content-independent by
construction. `punct` (0.614) is the other one that holds up.

**The old hand-picked composite (0.599) lost to plain equal weighting (0.649).**

### 1b.1b Where it lands on a second, independent group

The same corpus builder assembles a naturalist group — Darwin, Wallace, Huxley, Bates —
which was never fitted on. Composite macro AUC:

| corpus | contrast | composite |
|---|---|---|
| humorists (fitted on) | same era, same genre, 4 authors | **0.677** |
| naturalists (independent) | same era, same genre, 4 authors | **0.592** |
| Twain vs Darwin (independent) | different era-genre-topic — confounded | 0.614 |

Victorian scientific prose by four contemporaries is markedly harder than four comic
writers, which is unsurprising: a house style for scientific argument leaves less room
for personal surface habit than comic narration does. It is also the honest ceiling of
this feature set, and the clearest argument for the embedding tier in §3.

**Corpus hygiene turned out to matter as much as the metric.** The first naturalist
build scored 0.543. Gutenberg's top Darwin results include *Life and Letters* and *More
Letters* — compiled and edited by Francis Darwin, opening with a family genealogy table —
and Huxley's *Hume*, a biography of someone else. Those are contaminated positives:
prose filed under an author who did not write it. Filtering compilations,
correspondence and biographies (and requiring a single credited author) moved the same
metric from 0.543 to 0.592 without touching a line of scoring code. Any number from a
corpus nobody has inspected is suspect.

### 1b.2 Work-level leave-one-out is necessary but not sufficient

`vocab` still scores 0.763 — the best of anything — on a corpus where every author
writes in the same genre and no query shares a work with its reference. The reason is
worth stating: excluding the query's own work stops the obvious leak, but an author's
*whole body of work* is topically coherent. Twain's Mississippi books share vocabulary
with each other; Harte's mining stories share theirs.

So `vocab` is now excluded from the voice score **by construction, not by measurement**
(`metrics.VOICE_COMPONENTS`). An unconstrained fit hands it 0.54 of the weight and
reports a flattering held-out AUC of 0.858 — a number that would evaporate the first
time the author wrote about something new. It stays computed, because topic similarity
is exactly the right key for exemplar retrieval.

### 1b.3 Fitted weights

`revoice bench --fit` fits a penalised multivariate logistic model over the
content-independent components, on half the reference models, scored on the other half:

```
punct     0.392    delta     0.258    syntax    0.197    richness  0.069
fwbigram  0.033    opener    0.032    structure 0.020    ngram 0.000  rhythm 0.000
```

| corpus | old hand-picked | fitted |
|---|---|---|
| controlled (4 humorists, the design target) | 0.599 | **0.677** |
| controlled (4 naturalists, independent) | — | 0.592 |
| confounded (Twain vs Darwin, independent check) | 0.650 | 0.614 |

The trade is deliberate: +0.078 where the contrast is real, −0.036 where part of the
old number was genre detection. `rhythm` and `structure` fit to zero on every corpus
we have.

### 1b.4 The feature set

Added, all content-independent: **function-word bigrams** (joinery habits with no
subject matter in them), **sentence-opener class distribution**, **paragraph-shape
statistics** (the structural Writeprints family, previously absent), **punctuation
ratios** (semicolons per comma and so on — scale-free by construction),
**contraction and hyphenation rates**, and parser-free syntactic proxies
(subordination, conjunction-initial sentences).

Removed: `type_token_ratio` and `hapax_ratio`, both of which fall as a text grows, so
a band built from documents and applied to a paragraph was comparing two different
quantities. **Yule's K** and **MTLD** replace them — both length-stable by design.

### 1b.5 Minimal-touch, fixed

Calibration is now leave-one-out and bucketed by span length, with the buckets sampled
across their ranges rather than at their edges. The bands make the units error plain:

```
twain/professional:  25-40w -> 30.2    40-80w -> 38.7    80-160w -> 46.3    whole doc -> 50.7
```

A 20-point spread between the band for a paragraph and the band for a document — which
is exactly the gap that classified 79% of the author's own paragraphs as "rewrite".

`--strength` now sets how far below the band a span may sit before it is rewritten
(sigma 2 − 2·strength), so the dial controls a measured operating curve:

```
strength   sigma    author's own rewritten    foreign rewritten
   0.3      1.4              3%                     15%
   0.5      1.0              8%                     30%
   0.7      0.6             11%                     51%     <- default
   0.9      0.2             16%                     66%
```

**79% → 11%** on the author's own text at the default, against 51% of foreign text
caught. Where no span band exists the pipeline declines to judge and passes the span
through, because leaving rough text in is the cheap error and rewriting the author's
own prose is the expensive one.

## 1c. The comprehensive benchmark (70 authors, 11 genres)

Protocol: work-level leave-one-out, **hard negatives** (different author, *same genre*),
5,016 trials. `revoice bench bench-corpus --hard-negatives`.

```
scorer                      100w    400w    macro
vocab (tf-idf)             0.688   0.724    0.706   <- topic, excluded by construction
composite (fitted)         0.601   0.703    0.652
equal-weight               0.604   0.692    0.648
delta (Burrows)            0.567   0.655    0.611
ngram                      0.585   0.613    0.599
punct                      0.560   0.623    0.592
rhythm / opener / structure          ~0.52-0.56   (noise, fitted to zero)
```

### 1c.1 Difficulty is genre-dependent, and the spread is large

```
genre        authors  AUC     EER    tpr@5%fpr
humor            7   0.693   0.381     0.234
technical        9   0.674   0.389     0.296
adventure        6   0.628   0.426     0.134
travel           6   0.623   0.431     0.142
childrens        6   0.609   0.454     0.222
economics        6   0.605   0.440     0.139
essay            6   0.590   0.472     0.171
history          6   0.583   0.463     0.148
fiction          6   0.581   0.458     0.213
science          6   0.565   0.468     0.056
philosophy       6   0.553   0.486     0.097
```

Comic writers are the easiest to tell apart and academic philosophers the hardest — a
0.14 AUC spread between them. A single headline number would have hidden that, and the
per-genre answer is the more useful one for anyone deciding whether the measure is good
enough for *their* kind of writing.

**The good news for revoice specifically: `technical` is the second-easiest group**
(AUC 0.674, and the best operating point of any genre at 0.296 TPR @ 5% FPR).
Instructional and product prose — manuals, trade primers, clinical writing — carries
more personal surface habit than literary fiction does. That is the register most
revoice users write in, so the tool is strongest exactly where it needs to be.

### 1c.2 The previous weights were overfitted, and the bench caught it

Weights fitted on four humorists alone scored **0.631 on the 70-author corpus — below
plain equal weighting at 0.648**. Refitted across all 70 authors and 11 genres they
reach 0.652:

```
punct 0.332 · delta 0.318 · ngram 0.181 · richness 0.104 · structure 0.064
fwbigram / opener / syntax / rhythm / vocab: 0.000
```

What survives both fits is `punct` and `delta` — the two families that are
content-independent by construction. `ngram` returns with modest weight once the corpus
is broad enough that it cannot simply memorise one genre's vocabulary; on four humorists
it fitted to zero, on 70 authors across 11 genres it earns 0.181. `rhythm`, `opener`,
`syntax` and `structure` are measured as noise on both.

The general lesson: **fitting on one genre buys performance in that genre and loses it
everywhere else.** The four-humorist corpus was a large improvement over Twain-vs-Darwin
and still not enough.

### 1c.3 Honest status

`vocab` remains the single best-scoring component at 0.706 and remains excluded, because
what it measures is subject matter. Everything content-independent sits between 0.55 and
0.70 depending on genre, and Cllr stays near 0.94 — the ranking is usable, the absolute
numbers still carry little information. Minimal-touch works (11% of the author's own text
rewritten at strength 0.5, 52% of foreign text caught; 18%/70% at the 0.7 default), which
is what the metric is actually load-bearing for. Authorship attribution it is not.

## 1d. Voice as a vector, not a score (`revoice space`)

Everything above reports SIMILARITIES — "how close is this to that corpus on feature
family X". Those only mean anything relative to a chosen baseline, cannot be plotted,
and collapse to a number nobody can interrogate. `revoice/core/voicespace.py` adds
COORDINATES: 17 named axes, each an absolute measurement with a direction you can state
in words.

```
rhythm       sentence_length · sentence_variance
structure    paragraph_length · sentences_per_paragraph
lexis        word_length · lexical_richness · readability
syntax       subordination · nominalization · passivity · adverbial
punctuation  comma_density · punctuation_variety
stance       conjunction_openings · contraction · first_person · second_person
```

Coordinates are z-scored against a reference **population** (the benchmark corpus), so
`+1.4 on subordination` means "1.4 standard deviations more subordinate than typical
prose", which is a claim a person can check. A voice is then a **region** — centroid plus
spread — and any two voices compare directly without electing one as the reference.

**Every axis points the same way**: higher always means more of what the name says.
Yule's K falls as vocabulary widens, so `lexical_richness` negates it. A single
inverted axis would leave distances plausible while making every explanation backwards.

### 1d.1 It is more discriminative, not just more legible

Same protocol as the scalar benchmark — 70 authors, work-level LOO, hard negatives:

| measure | AUC |
|---|---|
| scalar composite (9 fitted similarity components) | 0.652 |
| **voice-space distance, per-voice spread normalised** | **0.689** |
| **voice-space distance, population sd only** | **0.699** |

Normalising by the voice's own spread is slightly *worse* — with a small reference set
the per-axis spread is itself noisy, and dividing by a noisy denominator costs more than
the tailoring gains.

### 1d.2 Per-axis discrimination

Which axes actually separate authors (AUC on same-author vs different-author pairs):

```
readability          0.706      comma_density         0.627
word_length          0.705      sentences_per_para    0.623
nominalization       0.702      conjunction_openings  0.619
paragraph_length     0.647      sentence_length       0.616
punctuation_variety  0.630      contraction           0.607
lexical_richness     0.630      passivity / adverbial 0.592
first_person         0.629      sentence_variance     0.589
                                subordination         0.563
```

Note that the best *single interpretable axis* (0.706) matches the entire fitted
nine-component similarity composite (0.652). Legibility is not costing accuracy here.

### 1d.3 Effective dimensionality: ~8, not 17

The axes are correlated — long sentences carry more commas, abstract nouns travel with
the passive — so 17 labels are not 17 degrees of freedom. The participation ratio of the
correlation matrix's eigenvalues gives:

```
effective dimensionality  7.77 of 17 axes    (top factor 28% of variance)
eigenvalues  4.80  2.19  1.56  1.30  1.15  0.98  0.82  0.73 ...
```

Two things follow. **Voice has roughly eight independent degrees of freedom** in this
feature set — adding a nineteenth correlated axis buys almost nothing, which is a useful
brake on feature-set sprawl. And **no single general "style factor" dominates** (the top
component is 28%, not 70%), so voice is genuinely multi-dimensional rather than one
sophistication scale wearing seventeen hats.

> The eigen-solver had a real bug that a known-answer test caught: naive power iteration
> with deflation restarted from the same vector, which after deflation lies in the
> null space, so the identity matrix returned `[1, 0, 0, 0]` instead of `[1, 1, 1, 1]`.
> The fix keeps found eigenvectors and projects them out, with basis-vector starts —
> a smooth start like `sin(c + i·d)` spans only a two-parameter family and stalls after
> two deflations.

## 1e. Reporting a similarity honestly (`revoice space --svg`)

A similarity number on its own invites a decision it cannot support. Measured against a
Twain reference built from 16 documents:

```
held-out Mark Twain              45.9   [31.9 – 49.1]
Bret Harte (same era, genre)     37.2   [25.2 – 45.9]     <- 14.0 points of overlap
US Federal Register rule         24.5   [18.7 – 29.8]
```

The 8.7-point gap between Twain and Harte reads as decisive; the intervals overlap
across 14 points, so the ordering is not evidence. The regulatory sample separates
cleanly. That is exactly the shape of a measure with AUC 0.69 — **confident about
register, weak about authorship** — and it is invisible without the interval.

**Where the interval comes from.** A bootstrap over the document's own paragraphs:
windows of ~220 words, coordinates computed once per window, windows resampled with
replacement 400 times, 5th and 95th percentiles reported. It answers *how much would
this move if I had been handed a different few pages of the same document* — not the
probability that the author is right, which this measure cannot give. Under three
windows there is nothing to resample, and the report says so rather than drawing a band
it cannot support.

**The chart** (`core/voicechart.py`) is dependency-free SVG: bar length is the size of a
per-axis difference, side is direction, whisker is the interval, and the number is
printed as well as drawn so nothing depends on colour alone. Colours are CSS custom
properties with literal fallbacks, so the same generator serves a written-out `.svg` and
an inline embed in a themed page.

One numerical guard worth recording: `VoiceRegion.spread` floors at 0.15 population
standard deviations. Without it, a voice fitted on near-identical reference texts gets a
spread near zero, deviations divide by it and come back in the millions, and every
similarity underflows to zero — the same failure mode the Burrows' Delta code already
guards against, arrived at independently.

## 2. What the field does

### 2.1 Classical track

- **Burrows' Delta** remains the reference method. Evert et al. (2017) showed **Cosine Delta**
  generally beats it, because cosine normalization removes vector magnitude from the comparison —
  which is exactly the length-sensitivity failure in §1.2/§1.4. It did not rescue us here, for the
  regime reason above, but it is the correct classical default when text is long enough.
- **Writeprints** (Abbasi & Chen) is the canonical handcrafted feature vector, organized as
  **lexical / syntactic / structural / content / idiosyncratic**. revoice currently has lexical and
  syntactic coverage and *no* structural or idiosyncratic features at all — no paragraph-length
  distribution, no habitual-error features.

### 2.2 Neural track (current SOTA)

Authorship has moved to contrastive embedding models that map text into a space where cosine
similarity *is* the authorship metric. This is precisely the "unique vector space with a
comparability metric" this project wants.

- **LUAR** — 82.5M params, Apache-2.0, contrastively trained on millions of Reddit authors.
  Critically for us, trained on **32-token excerpts**, i.e. built for short text.
- **StyleDistance** — roberta-base tuned on *synthetic near-exact paraphrases* across 40
  controlled style features, explicitly to strip content leakage.
- **STEB** (Rivera Soto, Wegmann, Aggazzotti) ranks these. LUAR variants and STAR lead the
  authorship tasks; **StyleDistance leads the content-controlled tasks (74.0 vs LUAR's 0.00 on
  STEL-or-Content)**. General-purpose embeddings lose badly — Qwen3-Embedding-8B, a top-5 MTEB
  model, scores 34.7. **Style is not a semantics problem**, and a general embedding model is the
  wrong tool.

### 2.2b Prior art: what other people have already built

Worth knowing before writing more code, because several of these solve problems we were
about to hit.

**Valla** (Tyo, Dhingra & Lipton, IJCNLP-AACL 2023) is the closest thing the field has to
what `revoice bench` is trying to be: a standardisation effort that fixes dataset splits
and metrics so methods can actually be compared, with **cross-topic, cross-genre and
unique-author challenge splits**, and a large Project Gutenberg dataset of its own. Its
diagnosis of the field is the same one we ran into: *"inconsistent dataset splits/filtering
and mismatched evaluation methods make it difficult to assess the state of the art."*
Named for Lorenzo Valla, who in 1440 exposed the Donation of Constantine as a forgery on
stylistic evidence.

Three of its findings change what we should build:

1. **A traditional n-gram model beat BERT on 5 of 7 attribution tasks** — 76.50% vs
   66.71% macro-accuracy. The classical track is not obsolete, and §3's embedding tier
   is less of a foregone conclusion than the STEB rankings alone suggest. BERT-based
   models won only on the two datasets with the *most words per author*, and on
   verification tasks.
2. **Hard-negative mining makes verification methods competitive with attribution
   methods.** That is precisely the `--hard-negatives` mode: draw the different-author
   trials from the same genre rather than from the whole corpus.
3. Their n-gram baseline is a **discriminative classifier trained per author**, not a
   distance to a centroid. That is a different shape from what revoice does, and it is
   the strongest single idea available to us: it needs negative examples at training
   time, which is exactly what the background author pool now provides.

**General Imposters (GI)** — Koppel & Winter, refined by Kestemont et al., shipped in the
R package `stylo` as `imposters()`. Rather than asking "are these two texts similar?", it
asks **"are they more similar to each other than to a pool of imposters, across many
randomly impaired feature spaces?"** Concretely: sample a random subset of features and a
random subset of imposter authors, check whether the candidate is still the nearest
neighbour, and repeat ~100 times. The proportion of iterations won is a score in [0, 1]
with a real meaning, and `imposters.optimize()` fits per-corpus decision thresholds
bracketing an explicit "don't know" zone.

This is the most directly adoptable idea in the literature for us. It fixes the failure
mode §1b keeps running into — a raw similarity that ranks acceptably but whose absolute
value means nothing — and it needs only the background pool the corpus builder now
produces. It also degrades honestly: near-0.5 scores are reported as inconclusive rather
than dressed up as an answer.

**Tooling worth reading rather than reinventing**: `stylo` (R, the reference
implementation for Delta variants, GI, and bootstrap consensus trees), `faststylometry`
(Python, Burrows' Delta with probability calibration), `pydelta` (Python, Delta variants).

**Standard datasets and why ours is still needed**: CCAT50/Reuters (50 journalists,
100 texts each), IMDb62 (62 users, 1000 reviews each), Blogs50. State-of-the-art hits
~98% on IMDb62, which the literature itself reads as *"the lack of challenging
attribution datasets"* rather than as a solved problem. All three are also modern,
short-form and topically noisy. None of them contain the register revoice exists to
serve — instructional, technical and product prose — which is why the corpus builder
includes a `technical` group.

### 2.3 Evaluation methodology (adopt wholesale)

- **STEL-or-Content** (Wegmann et al. 2022) — a content-controlled protocol that penalizes models
  relying on semantics. This is the published, citable test for the tf-idf leak in §1.2. Any
  component that cannot beat content-controlled pairs is measuring topic.
- **Forensic likelihood ratios.** Report an LR, not a raw score, and evaluate with **Cllr**
  (log-likelihood-ratio cost), which decomposes into discrimination cost (**Cllr_min**) and
  calibration cost (**Cllr_cal**). One headline number that punishes both bad ranking *and*
  overconfident scores. Calibration via **PAV** (pool-adjacent-violators isotonic regression) or
  logistic regression; PYLLR is the reference implementation to read. Both PAV and Cllr are
  ~40 lines of pure Python — **no dependency**.

### 2.4 The most relevant result to revoice's thesis

Recent LLM-personalization work ("the authorship gap", PersonalBench) evaluated four
personalization methods with three metrics. Three findings reshape our plan:

1. **The metrics do not correlate** — pairwise |r| < 0.07 between LUAR, an LLM-judge, and
   function-word cosine. They measure different constructs. **Blending them into one composite is
   incoherent**, which is exactly what revoice's six-component weighted composite does.
2. **Only the embedding metric had absolute meaning**, because it has two empirically measured
   reference bands: same-author ceiling 0.756, cross-author floor 0.626. Function-word cosine
   showed "collapsed baselines" (0.742–0.695) — no usable dynamic range. That is revoice's problem
   verbatim.
3. **All four prompt-based methods scored 0.484–0.508 — below the cross-author floor.** Prompted
   personalization left output stylistically closer to *random other authors* than to the target.
   This is a direct prediction that revoice's current prompt+exemplar approach does not work, and
   an empirical argument for the fine-tuning path. It is also the single strongest reason to build
   the instrument before building anything else: without it we cannot tell.

---

## 3. Design: three spaces, never blended

The core error to stop repeating is collapsing different constructs into one 0–100 number.

### Space 1 — Authorship (primary, learned, frozen)

A style embedding (LUAR or StyleDistance) maps any text of ≥ ~1 sentence to a vector. A voice is
the set of its corpus embeddings. The comparability metric is cosine — but **always reported
against two empirically measured distributions**:

- **same-author distribution**: corpus vs itself, leave-one-out
- **cross-author distribution**: corpus vs a background author pool

Output a **calibrated likelihood ratio**, scored by Cllr. This is the number that answers "is this
you?", it has absolute meaning across voices and lengths, and — unlike the Delta family — it works
at span length, which is revoice's actual operating point.

The model is frozen and shipped. This is not an LLM; it does not generate; it runs on CPU.

### Space 2 — Interpretable features (secondary, handcrafted, zero-dependency)

Keep the fingerprint. It is explainable, auditable, dependency-free, and it drives the
deterministic machinery (`lint`, hard swaps, `style.yaml`, the planned lexical-conformance check).
But:

- report it **per dimension**, validated per component — never as one weighted composite
- drop or fix the components §1.2 shows are noise
- **add the two missing Writeprints categories**: structural (paragraph-length distribution,
  sentence-position habits) and idiosyncratic (habitual spelling/punctuation quirks)
- replace TTR / hapax with **length-stable** richness measures (MTLD, Yule's K)
- add the cheap topic-independent features currently absent: function-word **bigrams**,
  sentence-opener class distribution, punctuation *sequences* and ratios (semicolons per comma,
  comma-before-*and* rate), clause-depth proxies (subordinator rate, commas per sentence),
  contraction rate

This space remains the always-available fallback so `stats` never hard-requires Space 1.

### Space 3 — Topic (retrieval only, never in the voice score)

tf-idf stays, but leaves the voice metric entirely. Its legitimate job is **exemplar retrieval** —
finding corpus passages near the span being rewritten, which is a real gap today (`pipeline.py`
serves the same 3 longest documents to every span in a register). Good at its real job, disastrous
inside an authorship score.

---

## 4. The bench (`revoice bench`) — built

A permanent, **LLM-free**, zero-dependency regression test. Deterministic given a seed.

```bash
revoice bench                              # the bundled Twain + Darwin packs
revoice bench data --queries 100 -o b.json # your own voices, more samples, full JSON
revoice bench --lengths 50,100,200 --no-content-control   # quick pass
```

Implemented in `revoice/core/bench.py` (protocol + reporting) and
`revoice/core/verify.py` (the statistics). The corpus layout is deliberately a voice
pack's — `<root>/<author>/training-data/*` with `<register>-<work>-<n>.md` filenames —
so `examples/voices` benches as-is and a purpose-built evaluation corpus (§4.1) drops in
beside it. Files that do not match the naming convention still load; they simply lose
topic control.

**What it reports**

- **AUC per query length** (50/100/200/400/800/1600 words). Never one aggregate: the
  measure's reliability is a function of length, and revoice's operating point is far
  below the regime classical stylometry was validated in.
- **Cllr, Cllr_min, Cllr_cal**, macro-averaged over lengths. Cllr_min comes from PAV
  isotonic regression (the discrimination floor); Cllr uses a 2-fold cross-validated
  logistic calibration, so it measures calibration that generalizes rather than a model
  that has already seen the trial it scores.
- **`tpr@fpr` — the operating point.** At a tolerable false-positive rate, what fraction
  of the author's own text do we keep untouched? *This*, not a composite, is what
  `pipeline.py` should consume.
- **Per-component ablation**, so weights get fit rather than guessed.
- **Content control** — the same trials under work-level vs document-level LOO. The AUC
  gap is the share of performance that was subject matter.
- **A verdict** in plain language. The bench answers the question; it does not just
  tabulate. It also refuses to let an untested length pass silently: a length with no
  trials is reported as *untested, not passing*.

**Two methodological commitments worth naming**, both learned the hard way while
building it:

- **Macro-average, never pool.** Concatenating trials of different lengths mixes score
  distributions with different means and yields an aggregate that can sit *below every
  one of its parts*. Since length-dependence is the finding, pooling would hide it. The
  pooled figures are retained in the JSON as `pooled_length_mixed`, marked.
- **Work-level LOO, not document-level.** Two documents from the same work share
  subject matter, so document-level LOO leaves the query's topic in its own reference.
  The difference is not cosmetic: the composite measures 0.773 the leaky way and 0.650
  under control (§1.3).

### 4.1 The evaluation corpus

`scripts/fetch_bench_corpus.py` builds it from public-domain Project Gutenberg texts.
**1,594 samples · 70 authors · 11 genres · 15.4 MB.** Written to a gitignored
`bench-corpus/`: freely re-fetchable, and derived data does not belong in the repo.

```
adventure   6 authors  141   doyle haggard kipling london stevenson wells
childrens   6 authors  140   alcott baum burnett carroll grahame nesbit
economics   6 authors  129   bagehot hobson malthus mill smith veblen
essay       6 authors  144   arnold burroughs carlyle chesterton emerson hazlitt
fiction     6 authors  144   austen dickens eliot hardy james wharton
history     6 authors  143   freeman froude macaulay motley parkman prescott
humor       7 authors  164   ade dunne harte jerome leacock nye twain
philosophy  6 authors  133   dewey hume james russell mill spencer
science     6 authors  131   darwin gosse huxley lyell tyndall wallace
technical   9 authors  190   hamilton harding hawkins leslie morgan osler parloa rorer wheatley
travel      6 authors  135   bird burton davis stanley taylor whymper
```

**Why these groups.** Within a genre the authors share era, language and register, so
telling them apart is authorship and nothing else — Twain against Bret Harte, not Twain
against Darwin. Across genres you get the easy contrast for comparison, plus the
background author pool that likelihood-ratio calibration and General Imposters both need.

**Why `technical` exists.** Manuals, trade primers, field guides, clinical writing and
cookery instruction — Morgan's *Wireless Telegraph Construction for Amateurs*, Hawkins'
*Electrical Guide*, Hamilton's printing-trade primers, Wheatley's *How to Make an Index*.
Instructional prose has its own conventions and is essentially absent from the standard
corpora (CCAT50, IMDb62, Blogs50 are all modern short-form web and news text). It is also
the register revoice's users actually write in, so a benchmark without it would measure
the wrong thing well.

**English originals only.** No translations: in a translated text the surface features
this measures belong to the translator, so a "Nietzsche" or "Tolstoy" label would be a
lie about who produced the prose.

### 4.2 The register corpus — modern functional prose

`scripts/fetch_register_corpus.py` builds a **second, separate** corpus: 140 documents
across five modern document types, labelled by register rather than author.

```
encyclopedic        30   Wikipedia                    CC BY-SA
scientific_article  30   Europe PMC open access       CC BY (filtered strictly)
regulatory          30   US Federal Register          public domain (17 USC 105)
technical_report    30   NASA NTRS                    public domain (17 USC 105)
press_release       20   NASA news                    public domain (17 USC 105)
```

**Why separate.** An authorship benchmark needs a reliable single author per document.
Web copy, scientific articles, regulatory notices and press releases are institutional
or multi-author — they cannot be authorship positives without lying about who wrote
them. They are exactly right for the *other* half of the problem: revoice's stated job
is register transfer, and until now every register measurement came from 19th-century
books. Provenance and licence are recorded per document in `manifest.json`.

**On "marketing brief":** there is no public-domain corpus of modern marketing copy, and
inventing one would be worse than not having it. Agency press releases are the closest
honest analogue — institutional promotional prose written to persuade a general
audience — and are labelled as what they are.

#### What the register corpus shows

Placed in the voice space alongside the literary corpus, the modern functional registers
occupy one corner of it — long words, heavy nominalisation, low readability, almost no
first or second person:

```
register             word_len  nominalzn  passivity  readability  1st person
scientific_article     +2.69     +2.03      +0.93      -1.92        -0.83
technical_report       +2.63     +1.98      +2.00      -1.93        -0.95
press_release          +2.01     +1.36      -0.46      -1.39        -0.89
encyclopedic           +1.59     +0.69      +0.87      -1.11        -0.96
regulatory             +1.56     +2.74      +0.07      -1.28        -0.78
19th-c technical       -0.17     -0.30      +0.09      +0.34        -0.64
```

**The finding that matters for revoice**: distance between register centroids puts
19th-century technical prose closer to *comic writing* (0.42) than to modern technical
reports (0.91). The instructional register has moved a long way in a century, so the
Gutenberg `technical` group is a poor proxy for how revoice's users actually write.
Any voice pack built to serve modern technical writing needs modern technical writing
in it.

Adding these registers also raises measured effective dimensionality from 7.77 to 8.2 —
modern functional prose exercises axes that 19th-century books leave flat.

#### Corpus hygiene is not a side issue

Four data bugs surfaced while building it, every one of which would have looked like a
metric failure:

| bug | consequence |
|---|---|
| substring name matching | "Whittier, John Greenleaf" matched *John Richard Green* — 58 works by the wrong man under one label |
| non-positional given names | "Smith, George Adam" (biblical scholar) filed as *Adam Smith*; "Bates, Walter" as *Henry Walter Bates* |
| `\bautobiograph\b` | never matches "Autobiography" — no word boundary before the "y", so the blocklist silently passed compilations |
| volumes counted as works | *Complete Writings* Vols 1-3 treated as three independent works, reinstating the topic leak work-level LOO exists to remove |

The first naturalist build scored AUC 0.543 and the second 0.592 — the same metric, on a
corpus with the compilations filtered out. **Any number from a corpus nobody has
inspected is suspect.** `tests/test_fetch_corpus.py` pins all four behaviours.

The builder is also catalogue-driven rather than API-driven: one static ~20 MB CSV from
Gutenberg instead of 70 gutendex calls, after gutendex went fully unreachable mid-build.
70 authors is 70 chances to fail; an offline join has none.

## 5. Dependency tiers

Measured, September 2026, macOS arm64 / cpython 3.12:

| tier | installed size | new deps | what it buys |
|---|---|---|---|
| **T0** — revoice today | 21 MB | — | current handcrafted vector |
| **T1** — fixed handcrafted vector + bench | **21 MB** | **none** | §1.5 bug fixes, §3 Space 2, §4 bench, Cllr/PAV |
| **T2** — ONNX style embedding | +126 MB | onnxruntime (75), numpy (21), tokenizers (9.4), hf-hub (11) | §3 Space 1 |
| **T3** — torch + transformers | +696 MB | ~15 packages | same 82M model, 5.5× the weight |

**T1 is free and must happen regardless.** It fixes real bugs, and — critically — it is what lets
us *measure whether T2 is worth it*. Build the bench before deciding on the dependency.

**If T2 is needed, take the ONNX path, not torch.** Same model, 5.5× lighter, and it fits the
longevity posture: onnxruntime is a self-contained inference runtime with no training framework
behind it. Details:

- torch/transformers are needed **once, offline, by us**, to export the checkpoint to ONNX. They
  become a dev-time extra (`[dev-export]`), never a user runtime dependency.
- `huggingface_hub` + `hf_xet` (~11 MB) are pulled by `tokenizers` only for *downloading*.
  Vendoring `tokenizer.json` and loading via `Tokenizer.from_file()` avoids them at runtime.
- int8-quantized ONNX for an 82M model is ~83 MB of weights; fp16 ~165 MB. Vendored into
  `params/archive/` alongside the GGUF, for the same archival reason.
- Make the embedding backend **pluggable exactly like `providers/`**, so `stats` degrades
  gracefully to Space 2 when it is absent, and so a better model can be swapped in later.

**T4, the durability floor (optional, later).** An 82M RoBERTa forward pass is ~150 lines of numpy
(embedding lookup, 12 × [attention + FFN + layernorm]). That drops onnxruntime entirely: numpy
only, ~21 MB. Slow — tens of milliseconds per span — but revoice states outright that speed is a
non-goal, and a numpy forward pass will still run in twenty years. This is the same argument as
llama.cpp/GGUF for the rewriter, applied to the metric. Worth doing once the model choice is
settled; not worth doing before.

**Caveat to validate, not assume:** LUAR is Reddit-trained and our corpora are literary and
technical prose. That domain shift is real and is exactly what the bench exists to measure.

---

## 6. Sequencing

1. ~~**Ship `revoice bench`.**~~ **Done** (0.1.1).
2. ~~**Build the eval corpus.**~~ **Done** (0.1.2) — `scripts/fetch_bench_corpus.py`,
   two era- and genre-matched groups of four authors, public domain, no LLM.
3. ~~**T1 — fix the handcrafted vector.**~~ **Done** (0.1.2): leave-one-out and
   span-bucketed calibration, tf-idf out of the voice score by construction, `rhythm`
   and `structure` measured as noise, length-stable richness, the missing structural
   and syntactic families added.
4. ~~**Fit the weights.**~~ **Done** (0.1.2) — `revoice bench --fit`.
5. ~~**Re-derive the pipeline threshold.**~~ **Done** (0.1.2): 79% → 11% of the
   author's own text rewritten, and `--strength` now drives a measured operating curve.
6. **Let the bench decide T2 (embeddings).** This is the next gating item, and §1b.1b
   is the argument for it: the handcrafted vector tops out around AUC 0.59-0.68, and on
   same-field scientific prose it is barely above chance. Score LUAR and StyleDistance
   on the identical protocol and adopt only on a margin that justifies 126 MB.
7. **Then** — model variants, prompt vs LoRA, 9B vs larger, base vs instruct.

**Honest status of the instrument.** It is now measured, calibrated in the right units,
and fitted rather than argued about, and it is good enough to keep minimal-touch from
mangling the author's own prose. It is *not* good enough to attribute authorship, and
`stats` output should be read as "how far from this corpus, roughly" rather than as a
verdict. Cllr sits near 0.9 on every corpus, meaning the numbers still carry little
information in absolute terms even where the ranking is usable.

## 7. Consequences for the rest of the system

- **`pipeline.py` attribution** consumes the calibrated operating point, not a raw composite.
- **The review flywheel** is currently recording labels produced by a misfiring classifier
  (§1.1). Every "accepted" rewrite of already-on-target text is a training pair teaching the model
  to over-edit. Fixing the metric is a prerequisite for collecting *any* flywheel data worth
  keeping.
- **`train.py`** should treat `reject` decisions as identity pairs (source → source). They are
  currently discarded entirely (`decision in ("accept", "edit")` and `src != tgt`), which throws
  away the strongest available minimal-touch signal.
- **The demo site** reports composites inflated by the tf-idf leak and should be regenerated once
  the metric is fixed.
- **`revoice/rubric/`** is unaffected. It answers a different question (quality of transfer, not
  distance from corpus), it stays optional, and per §2.4 its scores should never be averaged into
  the voice number.

---

## References

- Evert et al. (2017), *Understanding and explaining Delta measures for authorship attribution*, DSH 32(suppl_2) — https://academic.oup.com/dsh/article/32/suppl_2/ii4/3865676
- Wegmann & Nguyen (2021), *Does It Capture STEL? A Modular, Similarity-based Linguistic Style Evaluation Framework*, EMNLP — https://aclanthology.org/2021.emnlp-main.569/
- Patel et al. (2024), *StyleDistance: Stronger Content-Independent Style Embeddings with Synthetic Parallel Examples* — https://arxiv.org/abs/2410.12757
- Rivera Soto, Wegmann, Aggazzotti, *STEB: Style Text Embedding Benchmark* — https://arxiv.org/abs/2606.31741
- Rivera Soto et al. (2021), *Learning Universal Authorship Representations* (LUAR) — https://huggingface.co/rrivera1849/LUAR-MUD (Apache-2.0, 82.5M params)
- *Theory-Grounded Evaluation Exposes the Authorship Gap in LLM Personalization* — https://arxiv.org/abs/2604.26460
- Abbasi & Chen, *Writeprints: A Stylometric Approach to Identity-level Identification and Similarity Detection in Cyberspace* — https://www.scss.tcd.ie/Khurshid.Ahmad/Research/Sentiments/K_Teams_Buchraest/a7-abbasi.pdf
- Ishihara et al. (2022), *Likelihood ratio estimation for authorship text evidence: score- vs feature-based methods*, FSI — https://www.sciencedirect.com/science/article/abs/pii/S0379073822000986
- PYLLR — Python toolkit for likelihood-ratio calibration (BOSARIS port) — https://github.com/bsxfan/PYLLR
- PAN @ CLEF, authorship verification shared tasks — https://pan.webis.de/
- Tyo, Dhingra & Lipton (2023), *Valla: Standardizing and Benchmarking Authorship Attribution and Verification* — https://aclanthology.org/2023.ijcnlp-main.43/ · code https://github.com/JacobTyo/Valla
- Tyo, Dhingra & Lipton (2022), *On the State of the Art in Authorship Attribution and Authorship Verification* — https://arxiv.org/abs/2209.06869
- Kestemont et al., General Imposters, as implemented in `stylo` — https://computationalstylistics.github.io/blog/imposters/
- `stylo` (R) — https://github.com/computationalstylistics/stylo · `faststylometry` (Python) — https://github.com/fastdatascience/faststylometry
