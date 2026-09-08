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

## Previewing the site

```bash
python3 -m http.server 1138        # then http://localhost:1138/
```

(1138, not 8000 — nothing else will be squatting on it. The API server similarly
uses 7333.) The root page redirects to `pages/`; the demo needs http (not file://)
to load its baselines JSON.

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

## Releasing

`scripts/release.sh` cuts a release the way a person would: a pull request that CI must
pass before anything is merged or published. Four steps, each opting into more, and
nothing before `--pr` touches the remote.

```bash
./scripts/release.sh --patch            # verify + build, report what would happen
./scripts/release.sh --patch --commit   # bump and commit on a release branch, locally
./scripts/release.sh --patch --pr       # push the branch and open a PR into main
./scripts/release.sh --patch --release  # wait for CI green, squash-merge, tag, publish
```

Before running it, retitle the CHANGELOG's top section to `## X.Y.Z (unreleased)` for
the version you intend to ship. The script refuses to release a version the changelog
has no notes for, and refuses an empty section.

`--pr` and `--release` need the [GitHub CLI](https://cli.github.com) authenticated
(`gh auth login`).

### What it checks, cheapest failure first

1. the tag is free, the branch is known, `gh` is authenticated
2. the CHANGELOG has real notes for exactly this version
3. `pages/version.js`, `population.json` and `voices.json` regenerate — the site embeds
   the version and the metric's signature, and a stale one ships a lie
4. privacy gate · ruff · pytest at 100% coverage · the voice-metric bench
5. sdist **and** wheel build, then the wheel is installed into a throwaway venv and asked
   its version — the only check that catches a package that builds fine and is broken on
   arrival, such as a missing `package-data` entry
6. **the CI run GitHub performs against the PR is green** — `--release` blocks on it and
   refuses to merge or publish if it is red

Steps 1–5 run on your machine and are a fast filter, not the authority. Step 6 is the one
that decides: a release whose only evidence is "it passed on my laptop" is what this
script exists to prevent. Nothing before step 3 writes to your working tree, so a failed
run leaves the repo exactly as it found it.

### What ends up on GitHub

`main` only ever moves through a squash-merged PR. The merge commit is tagged `vX.Y.Z`,
and a GitHub Release is published with the CHANGELOG section as its notes and **the wheel
and sdist attached** — so the artefacts people download are the exact ones the script
built and test-installed, not a rebuild. GitHub Pages rebuilds from `pages/` on the merge.

### The engine versions

`revoice/rubric/` and `revoice/voicemetric/` carry their own version numbers and the
release script does *not* touch them. Bump those by hand in their own `__init__.py` when
their behaviour changes — for `voicemetric` that particularly means a MINOR bump whenever
the numbers move, which `signature()` reflects and `revoice status` then warns about for
any pack built under the old one.
