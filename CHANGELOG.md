# Changelog

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
