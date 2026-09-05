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

### 1.4 The numbers do not mean anything yet

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

### 1.5 Classical stylometry is out of regime here

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

### 1.6 Two outright bugs

- **Contaminated self-calibration.** `metrics.build_baselines()` scores each corpus document
  against a baseline *that includes that document*. The reported `self_mean` band is inflated.
  Fix: leave-one-out.
- **Length-dependent features inside a "shape" score.** `type_token_ratio` and `hapax_ratio` are
  both mathematically length-dependent and both live in `SCALARS`, feeding the `shape` component.
  They are part of why the composite drifts with length.

### 1.7 Coverage is not validation

The suite was 100% line coverage with zero discrimination assertions — `test_stylometry.py`
checks that `cosine(a, a) > 0.999`. Coverage tells us every line ran; nothing told us the
metric works. That gap is what `revoice bench` (§4) now closes.

---

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

### 4.1 The eval corpus is the real prerequisite

The bench is only as good as its corpus, and the bundled packs are not good enough — the
`800w`/`1600w` columns come back empty because no Twain document is long enough, and
Twain vs Darwin is confounded four ways (author, genre, topic, era), so a measure can
score well by detecting "humor vs natural history". We need:

- **positives**: same author, *different topic*
- **hard negatives**: different author, *same era and genre*
- **a background author pool** (dozens of authors) to estimate the cross-author
  distribution that Space 1's calibration requires

Public domain supplies all three. Hard negatives for Twain: 19th-c American humorists
(Bret Harte, Artemus Ward, George Ade, Bill Nye). For Darwin: 19th-c naturalists
(Wallace, Huxley, Bates, Lyell). The test that matters: **if the measure separates Twain
from Bret Harte, we have an instrument. If it only separates Twain from Darwin, we have a
topic detector.**

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

1. ~~**Ship `revoice bench`.**~~ **Done.** AUC/EER/Cllr by length, ablation, content
   control, verdict. Zero new dependencies, no LLM, wired into the test suite.
2. **Build the eval corpus** (§4.1). Topic-controlled positives, era/genre-matched hard
   negatives, background author pool. Public domain, no LLM. **This is now the gating
   item** — the harness is ready and the corpus is what limits it.
3. **T1 — fix the handcrafted vector** against bench numbers rather than intuition:
   leave-one-out self-calibration; tf-idf out of the voice score; drop or repair `rhythm`
   and `shape`; length-stable richness (MTLD / Yule's K) in place of TTR/hapax; add the
   missing structural and idiosyncratic Writeprints features; span-level length-bucketed
   calibration bands. Every change is now measurable the moment it lands.
4. **Fit the weights** on held-out labels instead of hand-picking them (§1.2).
5. **Let the bench decide T2.** Score the handcrafted vector, LUAR and StyleDistance on
   one protocol. Adopt the embedding only if it clears the free option by a margin that
   justifies 126 MB.
6. **Re-derive the pipeline threshold** from the bench's operating point (`tpr@fpr`)
   instead of `self_mean - self_std`. This is what fixes minimal-touch (§1.1).
7. *Only then* — model variants, prompt vs LoRA, 9B vs larger, base vs instruct. Every
   one of those is unanswerable until 1–6 exist, and straightforward afterwards.

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
