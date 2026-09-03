# Revoice — Architecture


> Design document. "Manufy" was the working name during early design; the tool is **revoice**.
*Working doc. Status: draft, in discussion.*

Pronounced **ma-NOO-fai**. (Spelling open: manufy / manufai / manoofai.)

A standalone, private document processor that rewrites text in Manu's voice ("manufies" it) while preserving all document structure. Input → manufy → manufied output, structure intact.

## Primary use case

Mostly technical writing, but the general job is **register transfer within one author**. Drafts arrive in a mix of sources and modes: Manu-fast-mode brain dumps, polished passages, pasted fragments, LLM-assisted text. Output is one chosen Manu register. Three jobs:

1. **Register restore.** Fast-mode brain dump → professional technical voice, or lighter short-story voice. Same author, different tone — this is not de-AI-ification, it's Manu-to-Manu transfer.
2. **De-AI-ify.** Strip LLM tells from assisted passages; LLM-hybrid prose is a major irritant.
3. **Homogenize.** Whatever the mix, the document leaves in a single consistent register.

Target register is an explicit parameter: `--voice technical | story | ...`, each backed by its own profile + exemplar bank from the corpus.

Quality bar: voice fidelity over everything. Speed explicitly does not matter — batch/overnight runs are fine.

**The hybrid-author problem.** The canonical failure: Manu writes something, an LLM "cleans it up," a few rounds of tweaking follow, and the result reads as a weird hybrid of two authors. Manufy's job is the *unification pass* at the end of that loop. Corollary — the **minimal-touch principle**: text already in the *target register* passes through byte-identical. Fast-mode Manu text is authentic but wrong-register, so it does get rewritten — into Manu's target voice, drawing phrasing from the corpus, never into generic LLM prose. Rewriting text that's already right is a worse failure than leaving rough text in. Manu likes writing; manufy exists to protect his sentences, not replace them.

## Principles

1. **API-first.** The core is a service. CLI, GUI, and pipelines are all clients of the same API.
2. **Structure is inviolable.** The LLM only ever sees text spans with IDs, never document structure. Structure loss is impossible by construction.
3. **Private by default, generic by design.** The engine is voice-agnostic; all author-specific state lives in a self-contained **voice pack**. Manu's deployment is just one voice pack. Style data never leaves the machine except to the configured LLM provider; local-only mode supported.
4. **Portable.** Python + uv/pipx. Single-file bitwrench GUI. No build step, no node toolchain.

## Stack

- **Core / server:** Python, FastAPI
- **GUI:** single `index.html` using bitwrench, served by FastAPI
- **CLI:** typer, wraps the same core library (can call core directly or hit a running server)
- **Doc parsing:** `markdown-it-py`/`mistune` (md), `python-docx`, `python-pptx`, plain text
- **LLM providers:** Anthropic API, OpenAI-compatible, Ollama (local)

## Three-pass rewrite model (v2 — supersedes pure span-isolation)

Span isolation came from the structure-preservation invariant (a compiler's model: parse,
transform leaves, reassemble). Right frame for safety, wrong frame for generation — writing
is read → plan → draft → edit. So:

- **Pass 0 — original_text_eval**: read the WHOLE input; combine deterministic signals
  (blend analysis, register attribution, size) with one LLM read that emits planning notes:
  doc type, arrival register(s), per-segment treatment, chunking seams for large docs,
  cautions ("math-dense — don't touch notation").
- **Pass 1 — generation**: conditioned on the brief + revoice params; chunked when large;
  rolling read-only context (previous chunk / doc opening, marked "context, do not rewrite").
  The span machinery stays underneath as the transaction log — IDs, minimal-touch,
  validation, diff all unchanged.
- **Pass 2 — cohesion edit**: over the assembled result, targeting seams (rewritten↔unchanged
  boundaries, chunk joints, broken references, register drift). Edits land as span diffs.
  Objective test: output heterogeneity (content-blend metric) should drop vs input.

Fine-tuning rationale, stated: register transfer is a mapping learned from examples, not a
skill followed from a description. Prompting = working memory (1K tokens of scaffolding per
span, model's own register pulling throughout); fine-tuning = skill in weights. FT also
shrinks prompts enough to make context-carrying chunked generation cheap on local models.
Passes 0 and 2 survive fine-tuning (FT fixes voice, not planning or seam repair). The
prompt pipeline is the instrument that manufactures the FT training set.

## Pipeline

```
input file
  → parser (md | txt | docx | pptx)
  → span extractor            # [{id, text, context}] — structure stays behind
  → cleanup pass              # fix obvious typos + punctuation errors (runs even at strength 0)
  → register attribution      # classify each span: on-target | Manu-wrong-register | foreign/AI | hybrid
  → style engine              # target-register profile + exemplars → prompt (or fine-tuned model)
  → rewrite pass              # LLM — on-target spans skip; everything else → target register
  → critique/repair pass      # LLM: "sounds like Manu? meaning preserved?"
  → validator (non-LLM)       # length ratio bounds, entities/numbers preserved, IDs intact
  → AI-tell lint (non-LLM)    # regex/heuristic scan for LLM tics that survived; flagged spans loop back
  → reassembler               # spans back into original structure
  → output file + diff report
```

Notes:
- docx/pptx edited **in place** (walk runs / text frames), never converted.
- Per-format constraints: pptx text frames get length caps; md code blocks/links/tables untouched.
- `--strength` dial (0–1): light touch → full rewrite. Strength 0 = cleanup only (proofread mode).

### Cleanup pass

Fixes objective errors regardless of strength: typos, doubled words, punctuation (missing periods, spacing, quote/apostrophe consistency), capitalization. Merged into the rewrite prompt at strength > 0; standalone LLM pass at strength 0. Validator treats cleanup edits as exempt from style checks but still enforces meaning/entity preservation. Diff view tags cleanup fixes separately from style rewrites so they can be reviewed (or auto-accepted) independently.

## API (service mode)

`revoice serve` starts FastAPI on localhost (bind/auth configurable for pipeline use). Two halves: **voice lifecycle** (build a voice) and **revoice** (use it).

**Parity rule:** every API endpoint has a CLI command and vice versa — both are thin clients of
the same core functions, so the whole tool is drivable from a console/SSH session with no server
running (CLI calls core directly) or against a remote instance (CLI `--server URL` mode, later).
Mapping: `voices add`→POST /voices · `learn`→build+status · `list-voices`/`status`→GET /voices ·
`run`→/revoice-file · `run -` (stdin)→/revoice · `stats`→/stats.

An example voice pack (Mark Twain, public domain, two registers) ships in `examples/voices/twain/`.

### Voice lifecycle

```
POST /v1/voices                        # addVoice: {name, metadata} → creates data/<name>/, returns upload target
POST /v1/voices/{name}/data            # add training docs (multipart or server-side path); ingestion into training-data/
POST /v1/voices/{name}/build           # kicks off pipeline: classify → index → profiles/exemplars →
                                       #   pair mining → (optional) LoRA train. Body: {mode: prompts | finetune}
GET  /v1/voices/{name}/status          # build progress + READINESS: not_ready | prompts_ready | finetune_ready
                                       #   (prompts_ready comes early — usable while LoRA still training)
GET  /v1/voices/{name}                 # manifest: registers found, doc counts, eval scores, adapter versions
DELETE /v1/voices/{name}               # remove pack
```

Build is staged and resumable: each stage (classify / profile / mine / train) is idempotent and cached; re-running after adding docs only processes deltas. Readiness is two-level by design — a voice becomes usable in prompt mode as soon as profiles + exemplars exist, and silently upgrades when the adapter lands.

### Revoice (inference)

```
POST /v1/revoice                       # sync text: {voice, text | spans, register, strength} → spans + diff
POST /v1/revoice-file                  # async: {voice, file (multipart or path), output_filename, register, strength} → job id
GET  /v1/jobs/{id}                     # status + progress
GET  /v1/jobs/{id}/result              # output file (named output_filename, same format as input)
GET  /v1/jobs/{id}/diff                # span-level diff + attribution (feeds GUI review)
POST /v1/stats                         # {voice?, register?, text|file} → descriptive stats + voice-match scores
GET  /v1/health
```

### Voice-match metrics (implemented; CLI `revoice stats`)

Deterministic authorship measures against per-register baselines built during `learn`:
Burrows' Delta (function-word z-scores; the authorship-attribution standard), char 3-gram +
word bigram profile cosine (strongest single features in the stylometry literature), sentence-length
histogram similarity (rhythm), tf-idf cosine vs register centroid (vocabulary), punctuation-rate and
scalar-feature similarity (word length, TTR, -ly adverbs, nominalizations, passive rate, Flesch).
Composite 0–100, calibrated per voice: `learn` scores the corpus against its own baselines and
reports self-score mean±std — judge documents relative to that band, not against 100. These same
metrics power the eval harness (Phase 2) and register attribution (input side).

- Sync endpoint enables pipelining: `cat draft.md | manufy - | ...` or curl from other tools.
- Auth: none on localhost by default; bearer token if bound to a network interface.
- Open question: streaming (SSE) for progressive results in GUI.

## Style engine

Three tiers, cumulative:

1. **Style profile** — distilled prose description of the voice (seed from existing `my-writing-style` skill). Editable, portable, versioned in `profiles/`.
2. **Exemplars** — 5–15 samples retrieved per document type (email vs. spec vs. slide). Stored alongside profile.
3. **Fine-tuned model** — see below.

`manufy learn <corpus-dir>` regenerates profile + exemplar bank. This is the moat.

### Style spec (`params/style.yaml`) — planned

Human-editable, machine-draftable three-layer spec, injected into the rewrite prompt:

1. **Rules** — explicit dos/don'ts ("short declarative after a long sentence").
2. **Phrase equivalences** — `"In any event," ← ["Now we...", "That said,"]`; hand-seeded, grown
   automatically from pair mining + review flywheel.
3. **Weighted lexicon** — e.g. `car: {automobile: .9, car: .09, "4 wheeler": .01}`. Key insight:
   LLMs can't execute probabilities (they mode-collapse to the top option), so the numbers are
   split by role: prompt gets *qualitative* rendering ("prefers automobile; occasionally car"),
   the deterministic post-pass gets the absolutes (hard swaps / never-words, same machinery as
   AI-tell lint), and the metrics/validator get the percentages — output lexical distributions
   are checked statistically against corpus-measured rates. Probabilities as measurement, not
   instruction. `learn` drafts the whole file from corpus counts; the author edits it.

### Register attribution

Per-span (sentence/paragraph) classifier against the *target register*: **on-target / Manu-wrong-register / foreign-AI / hybrid**. Signals: AI-tell lint hits, stylometric distance from the target register's corpus cluster (sentence-length distribution, function-word profile, punctuation habits), and an LLM judge with register exemplars as reference. Behavior:

- **on-target** → pass through byte-identical (cleanup fixes only, and only unambiguous ones).
- **Manu-wrong-register** (e.g. fast-mode brain dump) → rewrite into target register, leaning on corpus phrasing; keep Manu's word choices where they survive the register shift.
- **foreign/AI** → full rewrite at requested strength.
- **hybrid** → rewrite foreign clauses while preserving Manu's phrasing verbatim; prompt marks which parts scored as Manu.
- Diff view color-codes attribution so the classification itself is reviewable — a misclassified span is a bug Manu can see and correct (corrections feed the flywheel as classifier training data).
- The corpus makes this unusually tractable: per-genre clusters define each Manu register precisely, so "same author, different tone" is measurable, not vibes.

### AI-tell lint

A deterministic (non-LLM) checklist of LLM tics, maintained as a config file Manu can extend. Examples: "delve", "leverage", "It's not X, it's Y", "serves as a testament", rule-of-three parallel constructions, em-dash overuse, hedge-then-assert patterns, bolded-phrase-colon list items, "In conclusion" scaffolding. Runs on *output* — if the rewriter emits a tell, the span is flagged and re-rewritten with the violation named in the prompt. Also runnable on *input* (`manufy lint`) to show how AI-ified a draft is before processing.

The critique pass gets an explicit instruction: sounding like an LLM is a failure equal to changing meaning.

### Corpus

Manu has 100s–1000s of pre-LLM writing samples (short stories, poems, technical docs, and more), to be dropped in a `data/` folder. Assume it exists. Implications:

- **No cold start.** `learn` and fine-tuning are viable immediately — no need to wait for the review flywheel.
- **Clean provenance.** Zero LLM-generated text in the training signal; the style model learns the real voice.
- Poems likely excluded from rewrite exemplars by default (voice is real but register is wrong for docs); useful for the profile's vocabulary/rhythm analysis.

### Voice packs

One directory per voice; the engine never hardcodes an author. Drop-data-in, get-params-out:

```
data/
  <voice-name>/                # e.g. data/manu/
    training-data/             # drop everything here: md, txt, docx, pdf, ...
    params/                    # ALL generated state (rebuildable from training-data)
      index.jsonl              # corpus index (register/polish/domain per doc)
      profiles/                # per-register style profiles
      exemplars/               # per-register × domain exemplar banks
      lint.yaml                # AI-tell + voice-specific tells config
      pairs.jsonl              # mined + flywheel training pairs
      adapters/                # LoRA adapter(s) for the shared base model(s)
      manifest.json            # versions, base-model compat, eval scores
```

- `manufy learn data/<voice>` populates `params/` end-to-end (index → profiles → pairs → optionally train).
- One shared base model; each voice is a small hot-swappable LoRA adapter + retrieval banks. Serving multiple voices = loading different adapters.
- API/CLI take `--voice <name>`; single-voice installs default to the only pack present.
- A voice pack is portable and self-contained — copy the directory, move machines. `params/` is derived state: deletable, rebuildable.

### Corpus indexing (`manufy learn`, step 1)

An LLM classifier spins through `data/` first and tags every document (or section, for mixed docs) on three orthogonal axes:

| Axis | Values | Used for |
|---|---|---|
| **Register** | professional / casual / fiction / poetry / ... | target-voice profiles + exemplar banks |
| **Polish** | polished / draft / brain-dump | pair mining; brain-dumps define the *input* side of fast-mode |
| **Domain** | multi-label: electrical eng, economics, ... | exemplar retrieval relevance; domain vocab lists |

Output: `data/index.jsonl` (per-doc: path, axes, confidence, summary, stylometric fingerprint) — the substrate everything else queries. Axes' value sets are discovered from the corpus, not fixed in advance; classifier proposes, Manu can correct the taxonomy.

Downstream consumers:
1. **Profiles/exemplars** — per-register (× domain-weighted) banks built from `polished` docs only.
2. **Pair mining** — match draft/brain-dump docs to their polished descendants (same topic + domain, similar length, high content overlap) → real Manu-to-Manu training pairs, the gold standard.
3. **Fast-mode model** — brain-dump docs characterize what fast-mode input looks like, improving register attribution.
4. **De-manufy bootstrap** — sample across register × domain so synthetic pairs cover the space.

Index is cached; re-running `learn` only classifies new/changed files.

## Fine-tuning path

The pipeline generates its own training data: every reviewed job yields `(original span, manufied span, accept/reject/edit)` triples. Accepted and hand-edited pairs are gold.

- **Seed data:** the existing corpus itself. Bootstrap trick: have a frontier model *de-manufy* corpus samples into generic prose, giving `(generic, real-Manu)` pairs — hundreds of training examples before the tool is even used.
- **Data flywheel:** GUI review view (accept/reject/edit per span) writes to `training/pairs.jsonl` automatically. Use manufy normally; the dataset grows.
- **Target:** MLX LoRA/QLoRA on Apple Silicon (see Hardware & concrete models). Latency is a non-goal; voice fidelity is the only metric. Train on `original → manufied` pairs, conditioned on **target register** + strength. Manu-to-Manu pairs (fast-mode draft → its polished corpus version, where both survive) are the highest-value training data — if any drafts of corpus pieces still exist, they're gold. Fully private: weights and data never leave the machine.
- **Payoff:** the style lives in weights, not prompts. A large model tuned on pure pre-LLM Manu text can plausibly *beat* frontier prompting on voice — frontier models are the source of the AI-ification problem.
- **De-AI-ify pairs:** the de-manufy bootstrap is exactly the right training signal — generic/AI-flavored prose in, real Manu out. Bias the seed set toward technical writing (primary use case).
- **Sequence:** ship with prompt+exemplars first; first unsloth run on de-manufied corpus pairs alone, refined later with reviewed pairs from the flywheel. Provider interface stays identical — the fine-tuned model is just another backend.
- **Eval harness:** held-out corpus samples; score = AI-tell lint hits + a frontier judge comparing candidate vs. real Manu ("which was written by the human?"). Needed to compare LoRA runs objectively.
- Open questions: base model choice (Llama-3.x-70B, Qwen-72B, or a strong ~30B if VRAM-tight); whether critique pass stays frontier-model post-fine-tune (it judges, doesn't write, so AI-ification risk is low).

## Repo layout

```
manufy/
  core/          # parsers, span extractor, style engine, validator, reassembler
  providers/     # anthropic.py, openai_compat.py, ollama.py  (one interface: complete())
  cli.py         # typer
  server.py      # FastAPI + serves static/
  static/index.html   # bitwrench GUI: upload, side-by-side diff, accept/reject/edit
  data/          # voice packs: <voice>/training-data + <voice>/params (gitignored)
```

## Model strategy

Not small-LoRA *or* big-RAG — both, sequenced:

- **Small model (7–8B) + LoRA alone: no.** Style is surface-form and small models learn it, but manufy is rewrite-under-constraints (meaning, entities, span IDs, surgical hybrid edits). Small models trade AI-voice for meaning-drift — a worse failure.
- **Big model + exemplar retrieval alone: starting point, not endpoint.** Zero training cost, instant iteration, establishes the baseline. But large instruct models regress to their own register under pressure — exemplars mitigate, don't cure.
- **Endgame: LoRA on a mid-size base** — big enough for constraint-following, small enough for fast experiments.
- **Exemplar retrieval stays post-LoRA** (register/domain conditioning + vocabulary). **A large model stays as critic only** — it judges, never writes.
- All decisions arbitrated by the eval harness, never vibes.

### Hardware & concrete models (verified Aug 2026)

Machines: M1 Max 32GB + M5 Max 128GB. Training is rare and overnight is fine.

- **Training stack:** unsloth proper is CUDA/Triton-only → on Apple Silicon use **MLX**: `mlx_lm.lora` (LoRA/QLoRA/DoRA) or `mlx-tune` (unsloth-compatible API on MLX). 32GB Macs tune 7–9B comfortably; 128GB handles QLoRA up to ~70B.
- **Two tuned tiers:**
  - **Gemma 4 31B dense** — primary rewriter. QLoRA on M5 Max; inference ~20–24GB @ 4-bit (M5 comfortable; M1 Max tight-but-possible). Fallback if too tight on M1: Gemma 4 26B MoE (~14–18GB).
  - **Qwen3.5 9B** — portable tier. Tunable on either Mac, runs easily on the M1 Max. Same training set, same conditioning.
- **Untuned large model (M5 only):** gpt-oss-120b (65GB) or Qwen3.5-122B-A10B (70GB @ 4-bit, 10B active → fast) as Phase A rewriter and permanent critic/judge.
- Provider config selects per-machine: M5 = 31B LoRA + large critic; M1 = 9B LoRA (+ API critic optional).

### Archival runtime (the durability floor)

Everything must still run in 5+ years, untouched: uv.lock + pinned interpreter for the Python side,
optional vendored wheels, no JS toolchain (single-file bitwrench GUI). Provider APIs will drift, so
the guaranteed path is **llama.cpp + GGUF**: after fine-tuning, merge the LoRA and export a GGUF
into the voice pack (`params/archive/`), and vendor a llama.cpp source snapshot. llama.cpp is
dependency-free C/C++ and GGUF is self-contained — the whole system runs offline forever via the
existing `openai_compat` provider (llama.cpp server). The pinned model will be ancient eventually,
but ancient-and-writes-like-Manu beats state-of-the-art-and-410-Gone. No dependabot config —
deliberate, manual upgrades only.

## Plan

**Phase 0 — scaffold** (small)
Repo layout, provider interface (`complete()`), config, typer CLI skeleton.

**Phase 1 — corpus indexer**
LLM classifier over `data/` → `index.jsonl` (register / polish / domain axes, discovered taxonomy, per-section for mixed docs). Manu reviews/corrects taxonomy. Build per-register profiles + exemplar banks from polished docs.
*Milestone: `manufy learn data/` produces an index Manu agrees with.*

**Phase 2 — core pipeline (md/txt), Phase A model**
Parse → span extract → cleanup → register attribution → rewrite (big model + retrieved exemplars) → critique → validate → AI-tell lint → reassemble → diff. **Eval harness v0**: held-out corpus samples, lint score + human-vs-model judge.
*Milestone: `manufy draft.md --voice technical` produces output Manu would sign.*

**Phase 3 — service + GUI**
FastAPI job API (sync + async). GUI: single-file page built on **bitwrench (github.com/deftio/bitwrench — dogfooding)**; minimal but pretty, fully responsive (phone → desktop). Diff-review page: attribution color-coding, accept/reject/edit per span → training pairs. Launched via `revoice serve --gui`.
*Milestone: pipeline-able API + review flywheel running.*

**Phase 4 — training set**
Pair mining (draft/brain-dump → polished descendants from index) + de-manufy bootstrap (stratified by register × domain) + flywheel pairs.
*Milestone: training/pairs.jsonl with ~1k+ pairs, quality-checked.*

**Phase 5 — MLX LoRA**
Train Gemma-4-31B (M5) and Qwen3.5-9B (either Mac) on the same pairs; compare against Phase A on eval harness; iterate (data mix, strength conditioning). Winner becomes default rewriter; large model stays critic.
*Milestone: LoRA beats Phase A on blind voice-fidelity eval.*

**Phase 6 — docx, then pptx parsers**
Pure plumbing once the core is trusted.

## LLM I/O contract & rubric judging

- **Batch completions only** — the pipeline is an agentic loop over a completions API; no streaming,
  no chat state. Each stage: call → parse → next. Multiple calls to get the shape we want beats
  forcing one call to do everything.
- **No forced JSON on generation.** The rewrite call returns prose (JSON constraint measurably
  stiffens voice). Where structure is needed (classifier, profiles), JSON is requested and
  parse-validated with one retry; grammar enforcement used only where the backend offers it.
- **No LLM-generated numeric scores — ever.** Self-reported confidence (0.85...) is uncalibrated
  and unstable. All quality judgment uses **anchored categorical rubrics** (`params/rubrics.yaml`):
  per dimension (voice_fidelity, meaning_drift, verbosity, ...) a description, ordered named
  choices each with usage criteria, optional examples/counter-examples, and a weight. The critic
  answers one dimension per call, temperature 0, with exactly one choice name — no JSON needed.
  Choice→score mapping, weighting, and aggregation happen in code (deterministic, versioned).
  k=3 majority voting where it matters; the agreement rate is the honest confidence measure,
  derived not asserted. Rubric categories (not composites) are recorded per span — richer training
  signal for the flywheel ("foreign + drifted" beats "0.61").
- Rubric scores are the LLM half of the eval harness; stylometric metrics are the deterministic
  half. Different questions: distance-from-corpus vs quality-of-transfer.

## Watermarking (optional, later phase — under discussion)

Opt-in provenance marking of revoiced output (`--watermark`): steganographic embedding via
Unicode whitespace/zero-width variants, with an **LT fountain code** spreading a small payload
(doc id + timestamp + HMAC, ≤64 bits) across paragraphs — any sufficient subset of paragraphs
recovers it, so it survives excerpting and partial edits. `revoice watermark check` detects/decodes.
Constraints: never embed inside code spans, URLs, or identifiers; docx/pptx survive well, plain
md/txt is fragile (editors, linters, and copy-paste normalize invisible chars — and some tools now
flag zero-width chars as suspicious). Stylometric watermarking (steering word/punctuation choices)
is more robust but conflicts with voice fidelity — rejected. Off by default.

Second layer (post-fine-tune): **generation-time watermarking**. Once a voice runs as a
tuned local model, revoice controls weights and sampling — so it can bias token selection
statistically (SynthID-style logit watermarking, as Google/Anthropic do for their own model
output) with a detector keyed to the voice pack. Survives light editing far better than
whitespace steganography; complements spab's document-level fountain-coded payload.

## Open questions

- Streaming API responses (SSE) — worth it for GUI feel?
- Run-level formatting within a rewritten docx paragraph: dominant-run heuristic ok, or smarter mapping?
- Fine-tune locally (LoRA) vs. hosted — privacy vs. effort
- Doc-type detection: infer (email/spec/slide) or explicit flag?
