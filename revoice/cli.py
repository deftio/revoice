"""revoice CLI — rewrite documents in your own voice, structure preserved."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from revoice import __version__
from revoice.config import load_config
from revoice.core.voicepack import VoicePack, list_voices
from revoice.providers import make_provider

HELP = """
[bold]revoice[/bold] — rewrite documents in your own voice. Structure preserved, meaning preserved.

Typical workflow:

  [green]revoice voices add manu[/green]        create a voice pack
  ...drop your writing (md, txt, docx, pptx, pdf) into data/manu/training-data/ ...
  [green]revoice learn manu[/green]             classify corpus, build profiles + exemplars
  [green]revoice status manu[/green]            check readiness
  [green]revoice run draft.md -o out.md --voice manu --register technical[/green]
  [green]revoice serve --gui[/green]            start the API server and open the web UI

Config: ./revoice.yaml, ~/.config/revoice/config.yaml, or --config.
In-depth docs: [green]revoice help[/green]
(topics: workflow, registers, config, providers, voicepacks, pipeline, privacy)
"""

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
    help=HELP,
    epilog="Docs & source: https://github.com/deftio/revoice",
)
voices_app = typer.Typer(no_args_is_help=True, help="Create, list, and inspect voice packs.")
app.add_typer(voices_app, name="voices")

_cfg_opt = typer.Option(None, "--config", "-c", help="Path to revoice.yaml (default: ./revoice.yaml, then "
          "~/.config/revoice/config.yaml).")


def _version(v: bool):
    if v:
        typer.echo(f"revoice {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(False, "--version", "-V", callback=_version, is_eager=True, help="Print version and "
              "exit."),
):
    pass


def _pack(name: str, config: Path | None) -> tuple[VoicePack, object]:
    cfg = load_config(config)
    pack = VoicePack(cfg.data_dir / name)
    if not pack.exists():
        typer.secho(f"voice '{name}' not found under {cfg.data_dir}", fg="red")
        typer.echo(f"create it with: revoice voices add {name}")
        raise typer.Exit(1)
    return pack, cfg


@voices_app.command("add")
def voices_add(
    name: str = typer.Argument(..., help="Voice name, e.g. 'manu'. Becomes the directory data/<name>/."),
    config: Path = _cfg_opt,
):
    """Create a new voice pack: data/<name>/training-data (your samples) + data/<name>/params (derived state).

    Example: [green]revoice voices add manu[/green]
    """
    cfg = load_config(config)
    pack = VoicePack.create(cfg.data_dir, name)
    typer.secho(f"created {pack.root}", fg="green")
    typer.echo(f"next: drop writing samples into {pack.training_dir}")
    typer.echo(f"then: revoice learn {name}")


@voices_app.command("list")
def voices_list(config: Path = _cfg_opt):
    """List all voice packs and their readiness.

    Readiness: not_ready → prompts_ready (usable) → finetune_ready (LoRA adapter available).
    """
    cfg = load_config(config)
    packs = list_voices(cfg.data_dir)
    if not packs:
        typer.echo(f"no voices under {cfg.data_dir} — create one: revoice voices add <name>")
        return
    for p in packs:
        m = p.manifest()
        typer.echo(f"{p.name:20s} {m.get('readiness', '?'):16s} registers={m.get('registers', [])}")


@app.command("help")
def help_cmd(
    topic: str = typer.Argument(None, help="Topic name; omit to list all topics."),
):
    """Long-form documentation, man-page style. No internet required.

    Topics: workflow, registers, config, providers, voicepacks, pipeline, privacy.

    Examples: [green]revoice help[/green] · [green]revoice help registers[/green]
    """
    from rich.console import Console

    from revoice.helptext import TOPICS, topic_list

    console = Console()
    if not topic:
        console.print(topic_list())
        return
    if topic not in TOPICS:
        typer.secho(f"unknown topic '{topic}'", fg="red")
        console.print(topic_list())
        raise typer.Exit(1)
    console.print(TOPICS[topic][1])


@app.command("list-voices")
def list_voices_cmd(config: Path = _cfg_opt):
    """List local voice packs and readiness (alias of `revoice voices list`)."""
    voices_list(config)


@app.command()
def learn(
    name: str = typer.Argument(..., help="Voice to (re)build."),
    config: Path = _cfg_opt,
    verbose: bool = typer.Option(True, "--verbose/--quiet", help="Per-file classification output."),
):
    """Build (or update) a voice from its training data.

    Two stages:

    [bold]1. Index[/bold] — every file in training-data/ is classified by the configured
    classifier model on three axes: register (professional/casual/fiction/…, discovered
    from your corpus), polish (polished/draft/brain_dump), and subject domains.
    Results go to params/index.jsonl along with a stylometric fingerprint.

    [bold]2. Profiles[/bold] — for each register found: a distilled style profile
    (params/profiles/<register>.json) and an exemplar bank of your best excerpts
    (params/exemplars/<register>.json), built from polished docs only.

    [bold]Incremental[/bold]: files are keyed by content hash — re-run after adding or
    editing docs and only the changes are processed. One misclassified doc never
    aborts the run (counted in `errors`).

    Supported inputs: .md .txt .rst (always); .docx .pptx .pdf (with the extras:
    pip install "revoice[all]").

    Examples:
      [green]revoice learn manu[/green]
      [green]revoice learn manu --quiet[/green]          summary only
      [green]revoice learn manu -c prod.yaml[/green]     alternate config

    See also: [green]revoice help registers[/green] · [green]revoice help voicepacks[/green]
    """
    pack, cfg = _pack(name, config)
    provider = make_provider(cfg.classifier)

    def progress(item, msg):
        if verbose:
            typer.echo(f"  {item}: {msg}")

    typer.echo(f"[1/2] indexing {pack.training_dir} (classifier: {cfg.classifier.kind})")
    from revoice.core.indexer import index_corpus

    stats = index_corpus(pack, provider, progress)
    typer.echo(f"      {stats}")

    typer.echo("[2/3] building profiles + exemplar banks")
    from revoice.core.profiles import build_profiles

    built = build_profiles(pack, provider, progress)
    typer.echo(f"      registers: {built}")

    from revoice.core.rubrics import write_template as write_rubrics
    from revoice.core.style import write_template

    if write_template(pack.params_dir):
        typer.echo(f"      created {pack.params_dir / 'style.yaml'} (edit it: rules, phrases, lexicon, swaps)")
    if write_rubrics(pack.params_dir):
        typer.echo(f"      created {pack.params_dir / 'rubrics.yaml'} (judging dimensions incl. integrity)")

    typer.echo("[3/3] building stylometric baselines (voice-match metrics)")
    from revoice.core.metrics import build_baselines, load_calibration

    build_baselines(pack, progress)
    calib = load_calibration(pack)
    for reg, c in calib.items():
        typer.echo(f"  {reg}: self-score {c['self_mean']}±{c['self_std']} (min {c['self_min']})")
    typer.secho(f"readiness: {pack.manifest().get('readiness')}", fg="green")


@app.command()
def plan(
    input_file: Path = typer.Argument(..., help="Document to analyze."),
    voice: str = typer.Option(None, "--voice", "-v", help="Adds per-segment register attribution vs this voice."),
    register: str = typer.Option(None, "--register", "-r", help="Target register for attribution."),
    config: Path = _cfg_opt,
):
    """Pass 0 — deterministic original_text_eval. No LLM: doc kind, content blend,
    math/dialogue/citation densities, chunking seams, and per-segment treatment
    (revoice / pass-through / cleanup-only / protect) with cautions.

    Example: [green]revoice plan draft.md --voice manu -r technical[/green]
    """
    from revoice.core.ingest import extract_text
    from revoice.core.preflight import build_plan

    text = extract_text(input_file)
    if text is None:
        typer.secho(f"unsupported file type: {input_file.suffix}", fg="red")
        raise typer.Exit(1)
    pack = _pack(voice, config)[0] if voice else None
    typer.echo(json.dumps(build_plan(text, pack, register), ensure_ascii=False, indent=2))


@app.command()
def judge(
    original: Path = typer.Argument(..., help="The original document."),
    rewritten: Path = typer.Argument(..., help="The rewritten document to judge against it."),
    voice: str = typer.Option(None, "--voice", "-v", help="Voice pack whose rubrics.yaml to use (default: "
              "built-in rubrics)."),
    votes: int = typer.Option(1, "--votes", help="Judgments per dimension; majority wins, agreement recorded."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable verdicts."),
    config: Path = _cfg_opt,
):
    """Judge a rewrite against its original using anchored categorical rubrics.

    One critic call per dimension (voice_fidelity, integrity, verbosity, ai_register, …),
    temperature 0. The model answers with a choice NAME; scores, weights, and the
    composite are computed in code from rubrics.yaml. No LLM-generated numbers.

    Example: [green]revoice judge draft.md draft.revoiced.md --voice manu --votes 3[/green]
    """
    import yaml as _yaml

    from revoice.core.rubrics import TEMPLATE, judge_all, load_rubrics

    cfg = load_config(config)
    rubrics = load_rubrics(_pack(voice, config)[0].params_dir) if voice \
        else _yaml.safe_load(TEMPLATE)["dimensions"]
    critic = make_provider(cfg.critic)
    result = judge_all(critic, rubrics, original.read_text(), rewritten.read_text(),
                       votes, None if as_json else (lambda d, m: typer.echo(f"  {d}: {m}")))
    if as_json:
        typer.echo(json.dumps(result, indent=2))
    else:
        typer.secho(f"composite: {result['composite']}", bold=True)
        if result["rejected_by"]:
            typer.secho(f"REJECTED by: {', '.join(result['rejected_by'])}", fg="red")


@app.command()
def doctor(config: Path = _cfg_opt):
    """Diagnose the setup: config, providers (one raw round-trip each), and privacy —
    every voice pack should carry its protective .gitignore and be invisible to any
    surrounding git repo.

    Prints the exact raw model output so JSON/format problems are visible instead of silent.
    """
    cfg = load_config(config)
    typer.echo(f"data_dir: {cfg.data_dir}  (exists: {cfg.data_dir.is_dir()})")

    typer.echo("\n[privacy] voice packs are personal data")
    packs = list_voices(cfg.data_dir)
    if not packs:
        typer.echo("  no voice packs found")
    for p in packs:
        problems = []
        gi = p.root / ".gitignore"
        if not gi.is_file():
            problems.append("missing pack .gitignore (add one containing '*')")
        import subprocess

        try:
            rc = subprocess.run(
                ["git", "check-ignore", "-q", str(p.training_dir)],
                cwd=p.root, capture_output=True,
            ).returncode
            if rc == 1:
                problems.append("inside a git repo and NOT ignored — git would commit this pack!")
            elif rc == 0:
                pass  # ignored, good
            else:
                pass  # not a git repo — nothing to leak into
        except FileNotFoundError:
            pass  # git not installed — nothing to check
        if problems:
            for msg in problems:
                typer.secho(f"  {p.name}: {msg}", fg="red")
        else:
            typer.secho(f"  {p.name}: protected", fg="green")
    for role in ("classifier", "rewriter", "critic"):
        pc = getattr(cfg, role)
        typer.echo(f"\n[{role}] kind={pc.kind} model={pc.model or '(default)'} base_url={pc.base_url or '(default)'}")
        try:
            provider = make_provider(pc)
            raw = provider.complete(
                "You are a test. Respond with exactly this JSON and nothing else.",
                'Return {"ok": true, "who": "<your model name>"}',
            )
            typer.echo(f"  raw reply ({len(raw)} chars): {raw[:300]!r}")
            from revoice.providers.base import extract_json

            parsed = extract_json(raw)
            typer.secho(f"  JSON parse: OK -> {parsed}", fg="green")
        except Exception as e:  # noqa: BLE001
            typer.secho(f"  FAILED: {type(e).__name__}: {str(e)[:300]}", fg="red")


@app.command()
def status(
    name: str = typer.Argument(..., help="Voice to inspect."),
    config: Path = _cfg_opt,
):
    """Show a voice pack's manifest: readiness, registers found, index stats, adapter versions."""
    pack, _ = _pack(name, config)
    typer.echo(json.dumps(pack.manifest(), indent=2))


def _bar(v: float, width: int = 24) -> str:
    n = int(round(v * width))
    return "█" * n + "░" * (width - n)


@app.command()
def stats(
    input_file: Path = typer.Argument(..., help="Document to analyze (md, txt, docx, pptx, pdf)."),
    voice: str = typer.Option(None, "--voice", "-v", help="Compare against this voice's baselines."),
    register: str = typer.Option(None, "--register", "-r", help="Compare against one register only (default: all, "
              "best highlighted)."),
    fmt: str = typer.Option("text", "--format", "-f", help="Output format: text | json | md | html."),
    as_json: bool = typer.Option(False, "--json", help="Alias for --format json (same shape as the /v1/stats API)."),
    output: Path = typer.Option(None, "--output", "-o", help="Write report to a file instead of stdout "
              "(implied format from "
              "extension if --format omitted)."),
    config: Path = _cfg_opt,
):
    """Descriptive statistics for a document, and — with --voice — objective voice-match scores.

    All deterministic (no LLM): sentence/word distributions, function-word profile,
    punctuation habits, tf-idf vocabulary, plus similarity to a trained voice:

      [bold]delta[/bold]    Burrows' Delta on function-word z-scores (authorship standard; lower raw = closer)
      [bold]rhythm[/bold]   sentence-length histogram similarity
      [bold]vocab[/bold]    tf-idf cosine vs the register's corpus centroid
      [bold]punct[/bold]    punctuation-rate similarity
      [bold]shape[/bold]    scalar-feature similarity (word length, TTR, adverbs, passives, readability…)

    The composite (0-100) is calibrated per voice: `learn` reports the corpus's
    self-scores — compare against those, not against 100.

    Examples:
      [green]revoice stats draft.md[/green]                       descriptive only
      [green]revoice stats draft.md --voice manu[/green]          score vs every register
      [green]revoice stats draft.md -v manu -r professional --json[/green]
    """
    from revoice.core.ingest import extract_text
    from revoice.core.report import build_report, render_html, render_json, render_md

    text = extract_text(input_file)
    if text is None:
        typer.secho(f"unsupported file type: {input_file.suffix}", fg="red")
        raise typer.Exit(1)

    pack = _pack(voice, config)[0] if voice else None
    rep = build_report(text, source=input_file.name, pack=pack, register=register)

    if as_json:
        fmt = "json"
    elif fmt == "text" and output is not None:
        fmt = {".json": "json", ".md": "md", ".html": "html", ".htm": "html"}.get(output.suffix.lower(), "text")

    if fmt == "json":
        out = render_json(rep)
    elif fmt == "md":
        out = render_md(rep)
    elif fmt == "html":
        out = render_html(rep)
    elif fmt == "text":
        _print_fingerprint(input_file, rep["fingerprint"])
        _print_blend_report(rep["content"])
        if "match" in rep:
            m = rep["match"]
            typer.echo()
            typer.secho(f"voice match vs '{voice}':", bold=True)
            for reg, r in sorted(m["results"].items(), key=lambda kv: -kv[1]["composite"]):
                mark = "→" if reg == m["best_register"] else " "
                cal = r.get("calibration", {})
                cal_s = f"   (corpus self-score {cal['self_mean']}±{cal['self_std']})" if cal else ""
                typer.echo(f" {mark} {reg:14s} {r['composite']:5.1f}/100{cal_s}")
                c = r["components"]
                typer.echo(f"     delta {c['delta']:.2f} (raw {r['burrows_delta']})  ngram {c['ngram']:.2f}  "
                           f"rhythm {c['rhythm']:.2f}  vocab {c['vocab']:.2f}  "
                           f"punct {c['punct']:.2f}  shape {c['shape']:.2f}")
            if not m["results"][m["best_register"]].get("reliable", True):
                typer.secho("note: <150 words — scores are noisy at this length", fg="yellow")
        return
    else:
        typer.secho(f"unknown format '{fmt}' (text | json | md | html)", fg="red")
        raise typer.Exit(1)

    if output:
        output.write_text(out)
        typer.secho(f"→ {output}", fg="green")
    else:
        typer.echo(out)


def _print_fingerprint(input_file: Path, fp: dict):
    from revoice.core.stylometry import SENT_HIST_BINS

    typer.secho(f"{input_file}", bold=True)
    typer.echo(f"  {fp['words']} words · {fp['sentences']} sentences · "
               f"flesch {fp['flesch']} · type/token {fp['type_token_ratio']}")
    typer.echo(f"  sentence length: mean {fp['mean_sentence_len']} ± {fp['sentence_len_std']} "
               f"(burstiness {fp['burstiness']})")
    typer.echo("  sentence-length histogram (words/sentence):")
    labels = [f"{SENT_HIST_BINS[i]}-{SENT_HIST_BINS[i + 1] - 1}"
              if SENT_HIST_BINS[i + 1] < 10_000 else f"{SENT_HIST_BINS[i]}+"
              for i in range(len(SENT_HIST_BINS) - 1)]
    for lab, v in zip(labels, fp["sent_len_hist"], strict=False):
        typer.echo(f"    {lab:>6s} {_bar(v)} {v:.0%}")
    tops = sorted(fp["punct_per_sentence"].items(), key=lambda kv: -kv[1])[:5]
    typer.echo("  punctuation/sentence: " + "  ".join(f"{p} {v}" for p, v in tops))
    typer.echo(f"  -ly adverbs {fp['adverb_ly_rate']:.2%} · nominalizations {fp['nominalization_rate']:.2%} · "
               f"passive-ish {fp['passive_rate']:.2f}/sentence")


def _print_blend_report(b: dict):
    typer.echo("  content blend:")
    for t, frac in b["blend"].items():
        typer.echo(f"    {t:<11s} {_bar(frac)} {frac:.0%}")
    typer.echo(f"  {len(b['segments'])} segments · {b['type_switches']} type switches · "
               f"style heterogeneity {b['style_heterogeneity']:.2f}")
    color = {"homogeneous": "green", "mostly-uniform": "green",
             "blended": "yellow"}.get(b["verdict"], "red")
    typer.secho(f"  verdict: {b['verdict']}", fg=color)


@app.command()
def run(
    input_file: Path = typer.Argument(..., help="Document to revoice (md, txt; docx/pptx in Phase 6)."),
    output: Path = typer.Option(None, "--output", "-o", help="Output file (default: <input>.revoiced.<ext>)."),
    voice: str = typer.Option(None, "--voice", "-v", help="Voice pack to use (default: the only one present)."),
    register: str = typer.Option(None, "--register", "-r", help="Target register, e.g. technical, casual, fiction "
              "(default: inferred)."),
    strength: float = typer.Option(0.7, "--strength", "-s", min=0.0, max=1.0,
                                   help="0 = cleanup/proofread only … 1 = full rewrite."),
    critique: bool = typer.Option(False, "--critique",
                                  help="Judge each rewrite with the critic model against params/rubrics.yaml "
                                       "(one dimension per call); failing spans keep the original."),
    cohesion: bool = typer.Option(False, "--cohesion",
                                  help="Pass 2: final editing sweep over seams — fixes broken references/"
                                       "transitions between spans; unchanged spans stay unchanged."),
    votes: int = typer.Option(1, "--votes", help="Judgments per rubric dimension (majority wins; "
              "agreement rate recorded)."),
    raw: bool = typer.Option(False, "--raw", help="Print ONLY the revoiced text to stdout (no file, no "
              "chatter). Pipe-friendly."),
    as_json: bool = typer.Option(False, "--json", help="Print a JSON transformation record: input, output, per-span "
              "diff, before/after stats."),
    verbose: bool = typer.Option(True, "--verbose/--quiet", help="Per-span progress lines."),
    config: Path = _cfg_opt,
):
    """Revoice one document: rewrite it in your voice, structure preserved.

    Every span is attributed against the target register first — text that is
    already on-target passes through [bold]byte-identical[/bold]; brain-dump or
    AI-flavored spans are rewritten. Numbers, named entities, and document
    structure are validated after rewrite.

    [bold]--strength[/bold] controls how far to go:
      0.0   cleanup only (typos, punctuation) — a proofreader
      0.7   default: rewrite off-target spans, light touch elsewhere
      1.0   full rewrite of everything off-target

    [bold]--register[/bold] picks WHICH of your voices (see: revoice help registers).
    Omitted → inferred from the document.

    Output format always matches input format (md→md; docx/pptx in Phase 6).
    A span-level diff report is written next to the output as <output>.diff.json —
    the same shape the API and GUI review view use.

    Examples:
      [green]revoice run draft.md -o final.md --voice manu --register professional[/green]
      [green]revoice run notes.txt -s 1.0 -r fiction[/green]
      [green]revoice run - -o out.md[/green]                    read from stdin
    """
    import sys

    cfg = load_config(config)
    if voice is None:
        packs = list_voices(cfg.data_dir)
        if len(packs) != 1:
            typer.secho(f"--voice required ({len(packs)} voices found under {cfg.data_dir})", fg="red")
            raise typer.Exit(1)
        voice = packs[0].name
    pack, _ = _pack(voice, config)

    if str(input_file) == "-":
        text = sys.stdin.read()
        in_suffix = ".md"
    else:
        if input_file.suffix.lower() not in (".md", ".txt", ".markdown", ".text", ".rst"):
            typer.secho(f"{input_file.suffix}: only md/txt in Phase 2 (docx/pptx arrive in Phase 6)", fg="red")
            raise typer.Exit(1)
        text = input_file.read_text()
        in_suffix = input_file.suffix

    if output is None:
        base = Path("stdin") if str(input_file) == "-" else input_file
        output = base.with_suffix(f".revoiced{in_suffix}")

    from revoice.core.pipeline import revoice_document
    from revoice.providers import make_provider

    provider = make_provider(cfg.rewriter)
    quiet = raw or as_json or not verbose
    if not quiet:
        typer.echo(f"revoicing with voice '{voice}' (rewriter: {cfg.rewriter.kind}, strength {strength})")

    progress = None if quiet else (lambda sid, msg: typer.echo(f"  {sid}: {msg}"))
    critic = make_provider(cfg.critic) if critique else None
    out_text, report = revoice_document(text, pack, provider, register, strength, progress,
                                        critic=critic, judge_votes=votes, cohesion=cohesion)

    if raw:
        typer.echo(out_text)
        return
    if as_json:
        from revoice.core.stylometry import fingerprint

        record = {
            "voice": voice,
            "register": report["register"],
            "strength": strength,
            "input": text,
            "output": out_text,
            "summary": report["summary"],
            "spans": report["spans"],
            "stats_before": fingerprint(text),
            "stats_after": fingerprint(out_text),
        }
        if pack.params_dir.joinpath("baselines.json").is_file():
            from revoice.core.metrics import score_against_pack

            for key, t in (("match_before", text), ("match_after", out_text)):
                m = score_against_pack(t, pack, report["register"])
                r = m["results"][report["register"]]
                record[key] = {"composite": r["composite"], "components": r["components"]}
        typer.echo(json.dumps(record, ensure_ascii=False, indent=2))
        return

    output.write_text(out_text)
    diff_path = output.with_suffix(output.suffix + ".diff.json")
    diff_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    s = report["summary"]
    typer.secho(
        f"→ {output}  (register {report['register']}: {s.get('rewritten', 0)} rewritten, "
        f"{s.get('unchanged', 0)} untouched, "
        f"{s.get('validation-failed-kept-original', 0)} kept-after-failed-validation, "
        f"{s.get('error', 0)} errors)",
        fg="green",
    )
    typer.echo(f"  diff: {diff_path}")


@app.command()
def serve(
    config: Path = _cfg_opt,
    host: str = typer.Option("127.0.0.1", help="Bind address. Keep localhost unless you add auth."),
    port: int = typer.Option(7333, help="Port."),
    gui: bool = typer.Option(False, "--gui", help="Open the web UI in your browser after starting."),
):
    """Start the API server: voice lifecycle + revoice endpoints, and optionally the web UI.

    Endpoints (all under /v1):
      POST /voices, /voices/{name}/data, /voices/{name}/build   build a voice
      GET  /voices/{name}/status                                readiness
      POST /revoice                sync text → revoiced spans + diff
      POST /revoice-file           async file job → output file + reviewable diff
      GET  /jobs/{id}[/result|/diff]

    [bold]--gui[/bold] opens the web UI (bitwrench, single file): drop a file,
    review the span diff (attribution color-coded), accept/reject/edit — reviews
    feed the fine-tuning training set.

    Binds 127.0.0.1 by default; see [green]revoice help privacy[/green] before exposing.

    Auth: set REVOICE_TOKEN to require a bearer token (do this if binding beyond localhost).

    Examples:
      [green]revoice serve --gui[/green]
      [green]revoice serve --port 8900[/green]
    """
    url = f"http://{host}:{port}"
    typer.secho(f"revoice API on {url}  (GUI at {url}/, docs at {url}/docs)", fg="green")
    if gui:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    from revoice.server import serve as _serve

    _serve(config, host, port)


if __name__ == "__main__":
    app()
