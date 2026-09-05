# Changelog

## 0.1.1 (unreleased)

**The voice metric is now measured.** Everything revoice decides rests on one classifier
question — *is this passage already in the target voice?* — and nothing had ever tested it.
This release adds the instrument, and reports what it says.

### Added
- `revoice bench` + `revoice/core/bench.py` — an authorship-verification harness for the
  voice metric. **No LLM, no new dependencies**, deterministic given a seed. Reports AUC
  per query length, forensic calibration (Cllr / Cllr_min / Cllr_cal), the `tpr@fpr`
  operating point, a per-component ablation, a topic control, and a plain-language verdict.
  Corpus layout is a voice pack's, so `examples/voices` benches as-is.
- `revoice/core/verify.py` — verification statistics in pure stdlib: AUC (Mann-Whitney with
  tie handling), interpolated EER, `tpr_at_fpr`, PAV isotonic regression, Cllr with
  cross-validated logistic calibration. Known-answer tested against hand-derivable values.
- `metrics.baseline_from_texts()` — build a baseline from plain texts, so `learn` and the
  bench share one code path instead of two that drift.
- [`docs/metrics.md`](docs/metrics.md) — the voice-metric design doc: measurements, a survey
  of the authorship-verification literature (Cosine Delta, Writeprints, LUAR, StyleDistance,
  STEL-or-Content, forensic likelihood ratios), a three-space design, measured dependency
  tiers, and the sequencing that follows.

### What the measurements say
Under a topic-controlled protocol on the bundled packs, the shipped composite scores
**AUC 0.650** and **Cllr 0.941** (1.0 = a system that always answers "don't know"), and at a
5% false-positive rate keeps **14%** of the author's own text untouched. The `vocab`
component beats the whole composite and loses 0.162 AUC under topic control — it is largely
reading subject matter; `rhythm`, `delta` and `punct` sit near chance. Separately, the span
attribution threshold is calibrated in document-level units and applied to spans, so **79% of
the author's own paragraphs are classified "rewrite"**. The composite is not yet fit for the
decision the pipeline makes with it; `stats` output and the demo site should be read with
that in mind until it is fixed.

### Fixed
- `eer()` interpolates the ROC crossing instead of taking the best corner, which reported
  1.0 for an uninformative system whose true EER is 0.5.
- `build_baselines` no longer emits a degenerate baseline (empty n-gram and tf-idf centroids)
  for a register whose files have become unreadable; the register is skipped instead.

### Changed
- `docs/architecture.md` "Voice-match metrics" now points at `docs/metrics.md` and states
  plainly that the composite is implemented but not yet validated.

## 0.1.0 (unreleased)

Initial public release.

### Core
- Voice packs: `data/<voice>/training-data` in, fully-derived `params/` out;
  self-protecting `.gitignore` dropped in every pack (created or healed by `learn`)
- `learn`: corpus indexing (register / polish / domain), per-register style
  profiles + exemplar banks, stylometric baselines with self-calibration,
  editable `style.yaml` + `rubrics.yaml` templates
- `plan`: deterministic pass-0 document eval — doc kind, content blend,
  math/dialogue/citation/URL densities, chunking seams, per-segment treatment
  and cautions; zero LLM, drop-in
- `run`: three-pass md/txt rewrite — register attribution (minimal-touch:
  on-target spans pass byte-identical), rewriting with rolling read-only context
  and per-span cautions, numeric/entity/length validation, AI-tell lint with
  retry, style.yaml (rules / phrase equivalences / qualitative lexicon /
  deterministic hard swaps), optional `--cohesion` seam-editing pass, span-level
  diff with before/after heterogeneity; `--raw`, `--json`, `--critique`
- `stats`: descriptive fingerprint, content-blend detection
  (concatenated-dump detector), voice-match scoring (Burrows' Delta, char/word
  n-grams, rhythm, vocab, punctuation) calibrated against corpus self-scores;
  text / json / md / html reports
- `judge` + `revoice/rubric/`: generic anchored categorical judging — the model
  classifies, the code computes; distribution-aware agreement descriptors
  (winner share/gap, n_eff, k-normalized decisiveness); own README + examples
- `serve --gui`: FastAPI server with full CLI↔API parity (voices lifecycle,
  revoice sync/async jobs, stats, plan, judge, review) + single-file bitwrench
  review GUI; span accept/reject/edit writes training pairs (the fine-tuning
  flywheel)
- `doctor`: config + provider round-trip diagnostics, plus privacy checks
  (pack .gitignore present, pack invisible to any surrounding git repo)
- `train prep`: fine-tuning dataset builder — reviewed flywheel pairs
  (accept/edit) + de-voicing bootstrap ((generic → authentic) pairs from
  polished corpus windows) → deduped chat-format train/valid JSONL, plus
  generated per-backend tooling: `run_mlx.sh` (Apple Silicon, mlx_lm.lora),
  `train_unsloth.py` (CUDA), and a README covering serving the adapter
  (mlx_lm.server → openai_compat provider), GGUF archival export, and
  pre-adoption evaluation via `stats`/`judge`

### Providers
- ollama, anthropic, openrouter, openai_compat (llama.cpp / LM Studio / mlx_lm /
  vLLM / LiteLLM-proxy), stub (offline testing); thinking-trace suppression
  throughout; each isolated in a single small file

### Quality & safety
- 100% test coverage (120 tests, offline, no LLM required), zero-warning ruff lint
- CI privacy/secrets gate: refuses tracked user data, env/credential files, and
  secret-shaped values (value patterns, not env-var names; `gate: allow-secret`
  escape for deliberate fakes)

### Examples & site
- Example voice packs: Mark Twain (20 docs), Charles Darwin (22 docs) — public
  domain, Project Gutenberg, two registers each
- GitHub Pages site + in-browser voice-match demo (client-side stylometrics
  against exported baselines, self-score normalized)
