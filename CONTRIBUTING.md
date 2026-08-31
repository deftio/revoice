# Contributing to revoice

Thanks for your interest. revoice is early and moving; small focused PRs land best.

## Setup

```bash
git clone https://github.com/deftio/revoice && cd revoice
uv sync --all-extras
uv run pytest tests/ -q          # must pass, offline, no LLM needed (stub provider)
```

Python ≥ 3.10. `uv.lock` and `.python-version` are authoritative — don't bump deps
casually; this project upgrades deliberately (see "Longevity posture" in the README).

## Ground rules

- **No LLM required to test.** Everything must be testable with the stub provider;
  the suite runs offline and in CI. If your feature needs a model, mock the provider.
- **Structure is inviolable.** Any change to the pipeline must keep the round-trip
  guarantee: protected blocks byte-identical, spans reassemble exactly.
- **The model classifies, the code computes.** No LLM-generated numeric scores
  anywhere. Quality judgments go through anchored rubrics (`revoice/rubric/`).
- **Deterministic where possible.** Stats, attribution, preflight, validation, and
  lint are pure functions — keep them that way (no network, no randomness without
  a seed).
- **Small dependency tree.** New runtime deps need a strong reason; prefer stdlib.
  Providers stay isolated in single ~40-line files.
- **Coverage stays at 100%** (`uv run pytest --cov`). `# pragma: no cover` is for
  genuinely unexercisable glue (process entry points), not for skipping logic.
- **Lint is zero-warning**: `uv run ruff check revoice/ tests/ scripts/` must pass clean.
- **The privacy/secrets gate must pass**: `python scripts/check_no_user_data.py` — no
  tracked user data, env/credential files, or secret-shaped values. Deliberate fakes in
  tests need a `gate: allow-secret` comment on the same line. Repo admins: also enable
  GitHub push protection (Settings → Code security) as the broad-net layer.

## Style

- Python: type hints, docstrings on modules and non-obvious functions. Keep files
  small and single-purpose.
- GUI/pages: bitwrench (`bw.loadStyles()`, TACO objects, `bw_*` classes) — do not
  add custom CSS frameworks or build steps.
- CLI: every command gets real `--help` text with examples; long-form docs go in
  `revoice help <topic>` (helptext.py). API and CLI stay in parity.

## Adding a provider

Copy `revoice/providers/openai_compat.py`, implement `complete()`, register the
kind in `providers/__init__.py`, suppress thinking-traces if the backend emits
them, and add a mocked test in `tests/test_providers.py`.

## Voice packs & privacy

Never commit `data/` (personal corpora) or `revoice.yaml` (local config). Example
voices under `examples/voices/` must be public-domain text with source attribution
(see the Twain/Darwin READMEs for the pattern).

## Reporting issues

Include: `revoice doctor` output (redact keys), the command, and a minimal input
file that reproduces it. For voice-quality issues, include `revoice stats` output
for input and output — "sounds wrong" plus numbers beats "sounds wrong".

## License

BSD-2-Clause. By contributing you agree your contributions are licensed the same.
