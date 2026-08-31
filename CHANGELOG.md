# Changelog

## 0.1.0 (unreleased)

Initial public structure.

- Voice packs: `data/<voice>/training-data` in, fully-derived `params/` out
- `learn`: corpus indexing (register / polish / domain), per-register style
  profiles + exemplar banks, stylometric baselines with self-calibration
- `run`: md/txt rewrite pipeline — register attribution, minimal-touch rewriting,
  numeric/entity/length validation, AI-tell lint with retry, style.yaml
  (rules / phrase equivalences / qualitative lexicon / deterministic hard swaps),
  span-level diff; `--raw`, `--json`, `--critique`
- `stats`: descriptive fingerprint, content-blend detection (concatenated-dump
  detector), voice-match scoring (Burrows' Delta, char/word n-grams, rhythm,
  vocab, punctuation); text / json / md / html reports
- `plan`: deterministic pass-0 document eval — doc kind, densities, chunking
  seams, per-segment treatment + cautions; zero LLM
- `judge` + `revoice/rubric/`: anchored categorical judging (generic module),
  distribution-aware agreement descriptors (winner share/gap, n_eff, a_k)
- `serve --gui`: FastAPI server (full CLI parity) + single-file review GUI;
  span accept/reject/edit writes training pairs (the fine-tuning flywheel)
- Providers: ollama, anthropic, openrouter, openai_compat (llama.cpp / LM Studio /
  mlx_lm / vLLM), stub (offline testing); thinking-trace suppression throughout
- Example voice packs: Mark Twain (20 docs), Charles Darwin (22 docs) — public
  domain, from Project Gutenberg
