"""Long-form help topics for `revoice help <topic>`. Man-page-style, no web needed."""

TOPICS: dict[str, tuple[str, str]] = {
    "workflow": (
        "The full lifecycle, start to finish",
        """
[bold]THE REVOICE WORKFLOW[/bold]

1. Create a voice pack
     [green]revoice voices add manu[/green]
   Makes data/manu/training-data/ (yours) and data/manu/params/ (derived, rebuildable).

2. Add training data
   Drop writing samples into data/manu/training-data/ — any mix of .md .txt .docx
   .pptx .pdf, in any folder structure. More is better; hundreds of docs is great.
   Pre-LLM writing is ideal: it teaches the model YOUR voice, not an AI's.

3. Learn
     [green]revoice learn manu[/green]
   Classifies every document on three axes (register / polish / domain), writes
   params/index.jsonl, then builds per-register style profiles and exemplar banks.
   Incremental: re-run after adding files — unchanged docs are skipped (content hash).

4. Check readiness
     [green]revoice status manu[/green]
   readiness progresses:  not_ready → prompts_ready → finetune_ready
   prompts_ready means the voice is usable via prompting + exemplars.
   finetune_ready means a LoRA adapter exists (Phase 5, optional, better).

5. Revoice documents
     [green]revoice run draft.md -o final.md --voice manu --register professional[/green]
   Structure preserved, meaning preserved; spans already in your target voice pass
   through byte-identical.

6. Serve as an API / use the GUI
     [green]revoice serve --gui[/green]
   REST endpoints for pipelines plus a browser UI with span-level diff review.
   Reviewed accept/reject/edit decisions become future fine-tuning data.

See also:  revoice help registers | providers | config | voicepacks | privacy
""",
    ),
    "registers": (
        "Registers, polish levels, and domains explained",
        """
[bold]REGISTERS, POLISH, DOMAINS[/bold]

revoice models you as ONE author with SEVERAL voices ("registers"):

  register   the mode of writing — professional, casual, fiction, poetry, email …
             Discovered from your corpus during learn; not a fixed list. Each
             register gets its own style profile and exemplar bank.

  polish     how finished a document is:
               polished    final, representative of your best writing
               draft       readable but unfinished
               brain_dump  fast-mode notes, fragments, TODOs
             Only polished docs feed profiles/exemplars. draft/brain_dump docs
             teach revoice what your INPUT looks like, and (paired with their
             polished descendants) become gold fine-tuning data.

  domains    subject matter (electrical_engineering, economics, …). Used to pick
             the most relevant exemplars at rewrite time.

At rewrite time, every span is attributed against the TARGET register:

  on-target        already your voice in the right register → untouched, byte-identical
  wrong-register   your voice, wrong mode (e.g. brain dump) → rewritten to target
  foreign/AI       someone else's voice, incl. AI-flavored → fully rewritten
  hybrid           mixed → foreign clauses rewritten, your phrasing kept verbatim
""",
    ),
    "config": (
        "Configuration file reference",
        """
[bold]CONFIGURATION[/bold]

Search order: $REVOICE_CONFIG → ./revoice.yaml → ~/.config/revoice/config.yaml.
No file found → stub provider (offline, deterministic, smoke-testing only).

Three model roles, each independently configured:

  classifier   used by learn. Cheap and fast is fine.
  rewriter     produces revoiced text. The one that must nail your voice.
  critic       judges rewrites (voice? meaning?). Never writes output.

Full example:

  data_dir: data                # where voice packs live

  classifier:
    kind: ollama                # stub | anthropic | ollama | openai_compat
    model: gemma3:27b
    base_url: http://localhost:11434    # optional, this is the default

  rewriter:
    kind: openai_compat         # llama.cpp / LM Studio / mlx_lm.server / vLLM
    base_url: http://localhost:8080/v1
    model: my-tuned-31b
    temperature: 0.3
    max_tokens: 4096

  critic:
    kind: anthropic
    model: claude-sonnet-5
    api_key_env: ANTHROPIC_API_KEY      # env var holding the key

Fields: kind, model, base_url, api_key_env, max_tokens, temperature.
""",
    ),
    "providers": (
        "LLM backends: local and API",
        """
[bold]PROVIDERS[/bold]

  ollama          local. Talks to http://localhost:11434. Set model to any pulled
                  model (gemma3:27b, qwen3.5:9b, gpt-oss:120b …).

  openai_compat   any OpenAI-compatible endpoint: mlx_lm.server, LM Studio,
                  llama.cpp server, vLLM, or OpenAI itself. Set base_url; set
                  api_key_env if the endpoint needs a key.

  anthropic       Claude API. Needs ANTHROPIC_API_KEY (or your api_key_env).

  openrouter      one key, any hosted model. Set model to e.g.
                  "anthropic/claude-sonnet-5" or "qwen/qwen3.5-122b-a10b".
                  Needs OPENROUTER_API_KEY.

  stub            no LLM at all; canned deterministic replies. Lets the whole
                  pipeline run offline for testing. Never use for real output.

Fully-local privacy: use ollama/openai_compat for all three roles — nothing ever
leaves your machine. Mixed: local rewriter + API critic is a good compromise.
""",
    ),
    "voicepacks": (
        "Voice pack anatomy and portability",
        """
[bold]VOICE PACKS[/bold]

  data/<name>/
    training-data/     YOUR files. The only thing revoice will never modify.
    params/            ALL derived state — delete it and `learn` rebuilds it.
      index.jsonl      per-doc classification + stylometric fingerprint
      profiles/        <register>.json style profiles
      exemplars/       <register>.json exemplar banks
      pairs.jsonl      mined + reviewed training pairs        (Phase 4)
      adapters/        LoRA adapter weights                   (Phase 5)
      manifest.json    readiness, registers, stats, versions

Portable: the directory is self-contained — copy it to another machine and it
just works. Private: keep data/ out of version control (the default .gitignore
does). Multiple packs can coexist; --voice selects one, and single-pack installs
don't need the flag.
""",
    ),
    "privacy": (
        "What leaves your machine, and when",
        """
[bold]PRIVACY[/bold]

Your corpus and voice packs live on disk, under your control, gitignored.

What can leave the machine:
  - Text sent to whichever providers you configure. With anthropic (or a remote
    openai_compat endpoint), classified excerpts and rewrite spans go to that API.
  - With local providers only (ollama, localhost openai_compat): nothing, ever.

The server binds 127.0.0.1 by default. If you bind a network interface, add the
bearer-token auth — revoicing is a capability you may not want to share.

Fine-tuned adapters are files in your voice pack. Training (MLX, on-device) never
uploads anything.
""",
    ),
    "pipeline": (
        "What happens to a document during `run`",
        """
[bold]THE PIPELINE — three passes[/bold]

Pass 0 (deterministic; also standalone as `revoice plan`):
  whole-document eval: doc kind, content blend, math/dialogue/citation densities,
  chunking seams, per-segment treatment + cautions. Zero LLM.

Pass 1 (generation):
  parse            file → structural tree; span extract — the LLM NEVER sees structure
  attribution      each span scored against the target register (see: registers);
                   on-target spans pass through byte-identical
  rewrite          off-target spans rewritten with profile + exemplars + style.yaml,
                   per-span cautions (math/URLs/citations/quotes preserved), and
                   rolling read-only context from the previous span
  validate         deterministic: numbers/entities preserved, length bounds
  AI-tell lint     scans OUTPUT for LLM tics; violators re-rewritten once
  hard swaps       style.yaml `swaps` applied deterministically
  critique         optional --critique: anchored-rubric judging (voice_fidelity,
                   integrity, verbosity, ai_register); failing spans keep the original

Pass 2 (optional --cohesion):
  seam edit        rewritten spans re-checked against their preceding passage for
                   broken references/transitions; edits land as span diffs

emit: output file (same format) + span-level diff + heterogeneity before/after
(a properly revoiced document leaves MORE uniform than it arrived).

--strength 0.0 → cleanup/proofread only.  1.0 → full rewrite.  Default 0.7.
Failures worth knowing: revoice treats "rewrote text that was already right"
as a WORSE failure than "left rough text alone".
""",
    ),
}


def topic_list() -> str:
    lines = ["[bold]Help topics[/bold]  (revoice help <topic>)\n"]
    for name, (summary, _) in TOPICS.items():
        lines.append(f"  [green]{name:12s}[/green] {summary}")
    return "\n".join(lines)
