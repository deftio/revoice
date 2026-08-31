# revoice

[![License](https://img.shields.io/badge/License-BSD%202--Clause-blue.svg)](https://opensource.org/licenses/BSD-2-Clause)
[![CI](https://github.com/deftio/revoice/actions/workflows/ci.yml/badge.svg)](https://github.com/deftio/revoice/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/deftio/revoice)

**Rewrite documents in your own voice — structure preserved, meaning preserved.**

**[Site & live demo](https://deftio.github.io/revoice/)** — paste text, watch it scored
against Twain and Darwin in your browser.

Feed revoice your writing. It learns your registers (professional, casual, fiction, …),
then rewrites any document — brain dumps, AI-assisted drafts, mixed-source patchworks —
so it reads as *one* author: you. Text already in your target voice passes through
byte-identical. LLMs "AI-ify" prose; revoice is the antidote, and more generally a
**register-transfer engine within one author**.

Pronounced *ree-voice*. Local-first: runs entirely on your machine with Ollama or any
OpenAI-compatible server; cloud providers optional.

```
input ── parse ── plan (deterministic) ── attribute ── rewrite ── validate
      ── lint ── critique (rubrics) ── reassemble ── output + reviewable diff
```

## Highlights

- **Structure is inviolable.** The LLM only ever sees text spans with IDs — never
  document structure. Code blocks, tables, links, math, and citations survive by
  construction, not by hope.
- **Minimal-touch principle.** Every span is attributed against the target register
  (stylometrics: Burrows' Delta, char/word n-grams, rhythm, punctuation). On-target
  text is *not rewritten* — protecting your sentences is the point.
- **Voice packs are data.** `data/<voice>/training-data/` in → `params/` out (index,
  per-register profiles, exemplar banks, baselines, editable `style.yaml` +
  `rubrics.yaml`). Fully derived, rebuildable, portable — copy the directory.
- **Objective voice match.** `revoice stats` scores any document against a voice's
  corpus baselines, calibrated by the corpus's own self-scores — plus a content-blend
  detector that spots concatenated dumps of unrelated material.
- **Judgment without fake numbers.** Quality is judged by anchored categorical rubrics
  (see [`revoice/rubric/`](revoice/rubric/README.md)) — the model classifies, the code
  computes. Vote distributions get proper agreement descriptors (n_eff, winner gap,
  k-normalized decisiveness), never an LLM-asserted "0.85".
- **The flywheel.** Reviewing rewrites (accept / reject / edit, per span, in the GUI)
  writes training pairs — the dataset for fine-tuning a local model that *is* your
  voice (MLX LoRA path, llama.cpp/GGUF archival target).
- **CLI ⇄ API parity.** Every API endpoint is a CLI command and vice versa; both are
  thin clients of the same core. Pipeline it, script it, or click it.

## Install

**Requirements:** Python ≥ 3.10. For actual rewriting you also need an LLM backend —
either [Ollama](https://ollama.com) running locally (recommended, fully private) or an
API key (Anthropic / OpenRouter / any OpenAI-compatible endpoint). The deterministic
tools (`stats`, `plan`) and the test suite need no LLM at all.

**Option A — as a tool (recommended):**

```bash
pip install revoice            # or: pipx install revoice · uv tool install revoice
revoice --version
```

**Option B — from source** (to hack on it, or to get the bundled example voices):

```bash
git clone https://github.com/deftio/revoice && cd revoice
uv sync --all-extras           # exact pinned env via uv.lock (or: pip install -e ".[all]")
uv run revoice --version
```

The `[all]` extras add docx / pptx / pdf corpus ingestion; the base install handles
md / txt. (When installed from source with uv, prefix commands with `uv run`, or
`source .venv/bin/activate` once.)

**Verify the setup:**

```bash
revoice doctor                 # checks config + does one round-trip per provider
```

With no config file present, revoice uses a built-in offline stub — everything runs,
but rewrites are canned. Point it at a real model with a `revoice.yaml`:

```bash
cp revoice.example.yaml revoice.yaml   # self-documenting; defaults to local Ollama
```

## Quick start (60 seconds, with the bundled Twain voice)

From a source checkout (the examples ship in the repo):

```bash
cp revoice.example.yaml revoice.yaml           # edit models if needed
mkdir -p data && cp -r examples/voices/twain data/twain

revoice learn twain                            # index corpus -> profiles -> baselines
echo "gotta fix the intro, it reads all wrong maybe rework the ending too" > draft.md
revoice run draft.md -o out.md --voice twain --register fiction -s 1.0
revoice stats draft.md --voice twain           # objective voice match, no LLM needed
revoice serve --gui                            # API + review GUI in the browser
```

## Make your own voice

```bash
revoice voices add you
# drop your writing into data/you/training-data/  (md, txt, docx, pptx, pdf — any mix)
revoice learn you
revoice run anything.md -o anything.you.md --voice you
```

More corpus is better — dozens of documents works, hundreds is excellent, and
pre-LLM writing is ideal (it teaches your voice, not an AI's). `revoice help workflow`
walks the whole lifecycle.

**Privacy:** a voice pack is personal data — your corpus, plus derived profiles and
review pairs that describe how you write. Packs are self-protecting: `voices add`
drops a `.gitignore` (`*`) inside the pack, so its contents stay out of git wherever
the directory is copied — independent of this repo's ignore rules. Nothing leaves
your machine unless you configure a cloud provider (and `revoice help privacy`
spells out exactly what goes where).

## CLI

| command | does |
|---|---|
| `revoice voices add / list-voices` | create / list voice packs |
| `revoice learn <voice>` | classify corpus → index, profiles, exemplars, baselines (incremental) |
| `revoice plan <file>` | deterministic pass-0 doc eval: kind, densities, chunk seams, per-segment treatment — zero LLM |
| `revoice run <file>` | revoice a document (`--strength`, `--register`, `--critique`, `--raw`, `--json`) |
| `revoice stats <file>` | fingerprint + content blend + voice match (`--format text\|json\|md\|html`) |
| `revoice judge a b` | rubric-judge a rewrite against its original |
| `revoice serve --gui` | API server + single-file review GUI |
| `revoice doctor` | config + provider diagnostics with raw model replies |
| `revoice help <topic>` | man-page-style docs: workflow, registers, config, providers, voicepacks, pipeline, privacy |

## Configuration

Three model roles in `revoice.yaml` — classifier (cheap), rewriter (must nail the
voice), critic (judges, never writes). Providers: `ollama`, `openai_compat`
(llama.cpp / LM Studio / mlx_lm / vLLM / LiteLLM-proxy), `anthropic`, `openrouter`,
`stub` (offline). See [`revoice.example.yaml`](revoice.example.yaml) — it's
self-documenting. Fully-local privacy: use local providers for all three roles and
nothing ever leaves your machine.

## Longevity posture

Built to still run, untouched, in five years: locked deps (`uv.lock` + pinned
interpreter uv installs itself), a small boring dependency tree, a pure-stdlib
stats core, a no-build-step single-file GUI, providers isolated in ~40-line files,
and an archival inference path (merged-LoRA → GGUF + vendored llama.cpp) so a tuned
voice outlives every API it ever called. No dependabot; upgrades are deliberate.

## Project layout

```
revoice/           the package
  core/            spans, stylometry, metrics, segments, preflight, pipeline,
                   indexer, profiles, style, lint, rubrics, report, voicepack
  providers/       ollama, anthropic, openrouter, openai_compat, stub
  rubric/          generic anchored-rubric judging (standalone; own README)
  static/          the GUI (one HTML file)
  cli.py serve.py  typer CLI · FastAPI server
docs/architecture.md   full design doc (three-pass model, fine-tuning path, roadmap)
examples/voices/       twain/ and darwin/ demo corpora (public domain)
tests/                 pytest suite (stub provider — runs offline)
```

## Status & roadmap

Working today — the full three-pass pipeline: `plan` (deterministic pass-0 eval) →
`run` (attribution, context-carrying rewrite, validation, lint, style.yaml, rubric
critique, optional `--cohesion` seam pass) → reviewable diff with before/after
heterogeneity. Plus `learn`, `stats` (4 output formats), `judge`, `serve --gui`
(full CLI↔API parity + review flywheel), `doctor` (incl. privacy checks), 100%
test coverage, zero-warning lint, and a CI gate against committed user data or
secrets. Next: pair mining + de-voicing bootstrap (Phase 4), MLX LoRA fine-tuning
+ GGUF archival export (Phase 5), docx/pptx round-trip (Phase 6).
Details: [docs/architecture.md](docs/architecture.md).

## License

BSD-2-Clause © deftio
