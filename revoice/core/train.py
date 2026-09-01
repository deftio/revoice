"""Phase 5: build the fine-tuning dataset and per-backend training tooling.

revoice does NOT vendor a training framework. It produces:
  params/train/train.jsonl + valid.jsonl   chat-format examples (works with both
                                           mlx_lm.lora --data and unsloth/HF datasets)
  params/train/run_mlx.sh                  mlx_lm.lora LoRA run (Apple Silicon)
  params/train/train_unsloth.py            unsloth SFT script (CUDA)
  params/train/README.md                   how to run, then export GGUF for archival

Data sources:
  1. Review flywheel (params/pairs.jsonl): accept -> (original, model_output);
     edit -> (original, edited final) — the gold standard.
  2. De-voicing bootstrap: an LLM rewrites polished corpus windows into plain
     generic prose, giving (generic -> authentic) pairs — the exact mapping the
     rewriter must learn, available before the tool has any usage history.

Every example: system = compact conditioning (voice + register), user = source
text, assistant = authentic text. The fine-tuned model is then just another
openai_compat/ollama provider.
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone

from revoice.core.ingest import extract_text
from revoice.core.voicepack import VoicePack
from revoice.providers.base import Provider

DEVOICE_SYSTEM = """DEVOICE_PASSAGE
Rewrite the passage into plain, neutral, generic prose. Remove everything
distinctive about the author's voice: rhythm, characteristic word choices,
irony, idiosyncratic punctuation. Preserve meaning, facts, names, and numbers
exactly. Output only the rewritten passage."""

SYSTEM_TMPL = ("Rewrite the text in the voice of {voice} ({register} register). "
               "Preserve meaning, names, and numbers exactly.")

WINDOW_CHARS = 1100
MIN_WINDOW_CHARS = 350


def _windows(text: str, target: int = WINDOW_CHARS) -> list[str]:
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur, size = [], [], 0
    for p in paras:
        cur.append(p)
        size += len(p)
        if size >= target:
            out.append("\n\n".join(cur))
            cur, size = [], 0
    if cur:
        out.append("\n\n".join(cur))
    return [w.strip() for w in out if len(w.strip()) >= MIN_WINDOW_CHARS]


def _example(voice: str, register: str, source: str, target: str, origin: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_TMPL.format(voice=voice, register=register)},
            {"role": "user", "content": source},
            {"role": "assistant", "content": target},
        ],
        "meta": {"origin": origin, "register": register},
    }


def flywheel_examples(pack: VoicePack) -> list[dict]:
    """Reviewed pairs: accept and edit decisions become training examples."""
    f = pack.params_dir / "pairs.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("decision") not in ("accept", "edit"):
            continue
        src, tgt = rec.get("original"), rec.get("final")
        if src and tgt and src.strip() != tgt.strip():
            out.append(_example(pack.name, rec.get("register") or "default", src, tgt,
                                f"flywheel-{rec['decision']}"))
    return out


def bootstrap_examples(pack: VoicePack, provider: Provider, max_pairs: int = 200,
                       progress=None) -> list[dict]:
    """De-voice polished corpus windows -> (generic, authentic) pairs."""
    index = pack.read_index()
    polished = [e for e in index.values() if e.get("polish") == "polished"] or list(index.values())
    out = []
    for e in polished:
        if len(out) >= max_pairs:
            break
        text = extract_text(pack.training_dir / e["path"])
        if not text:
            continue
        for w in _windows(text):
            if len(out) >= max_pairs:
                break
            try:
                generic = provider.complete(DEVOICE_SYSTEM, w).strip()
            except Exception as exc:  # noqa: BLE001 — one failure never kills the run
                if progress:
                    progress(e["path"], f"ERROR: {exc}")
                continue
            if generic and generic != w:
                out.append(_example(pack.name, e.get("register", "default"), generic, w, "devoice"))
                if progress:
                    progress(e["path"], f"pair {len(out)}")
    return out


def build_dataset(pack: VoicePack, provider: Provider | None = None, bootstrap_n: int = 200,
                  valid_frac: float = 0.1, seed: int = 17, progress=None) -> dict:
    """Assemble, dedup, split, and write params/train/{train,valid}.jsonl."""
    examples = flywheel_examples(pack)
    n_flywheel = len(examples)
    if provider is not None and bootstrap_n > 0:
        examples += bootstrap_examples(pack, provider, bootstrap_n, progress)

    # dedup on (source, target)
    seen, unique = set(), []
    for ex in examples:
        key = (ex["messages"][1]["content"], ex["messages"][2]["content"])
        if key not in seen:
            seen.add(key)
            unique.append(ex)

    rng = random.Random(seed)
    rng.shuffle(unique)
    n_valid = max(1, int(len(unique) * valid_frac)) if len(unique) > 1 else 0
    valid, train = unique[:n_valid], unique[n_valid:]

    tdir = pack.params_dir / "train"
    tdir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", train), ("valid", valid)):
        with (tdir / f"{name}.jsonl").open("w") as f:
            for ex in rows:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    stats = {"total": len(unique), "train": len(train), "valid": len(valid),
             "flywheel": n_flywheel, "bootstrap": len(unique) - min(n_flywheel, len(unique)),
             "built": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (tdir / "stats.json").write_text(json.dumps(stats, indent=2))
    pack.update_manifest(train_stats=stats)
    return stats


# ---------- backend tooling ----------

MLX_SH = """#!/bin/sh
# LoRA fine-tune on Apple Silicon via mlx_lm. Run from this directory.
#   pip install mlx-lm     (or: uv tool install mlx-lm)
# Latency is a non-goal; overnight is fine. Adjust --iters to taste.
set -e
MODEL="{base_model}"
mlx_lm.lora \\
  --model "$MODEL" \\
  --train \\
  --data . \\
  --adapter-path adapters \\
  --batch-size 2 --num-layers 16 --iters 1000 \\
  --learning-rate 1e-5

echo "adapter written to adapters/ — test it:"
echo "  mlx_lm.generate --model $MODEL --adapter-path adapters --prompt '...'"
echo "serve it for revoice (openai_compat provider, base_url http://localhost:8080/v1):"
echo "  mlx_lm.server --model $MODEL --adapter-path adapters --port 8080"
"""

UNSLOTH_PY = '''"""LoRA fine-tune via unsloth (CUDA). Run: python train_unsloth.py
Requires: pip install unsloth datasets trl
"""

from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer

BASE_MODEL = "{base_model}"
MAX_SEQ = 4096

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL, max_seq_length=MAX_SEQ, load_in_4bit=True,
)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
)

def to_text(ex):
    return {{"text": tokenizer.apply_chat_template(ex["messages"], tokenize=False)}}

train = load_dataset("json", data_files="train.jsonl", split="train").map(to_text)
valid = load_dataset("json", data_files="valid.jsonl", split="train").map(to_text)

trainer = SFTTrainer(
    model=model, tokenizer=tokenizer,
    train_dataset=train, eval_dataset=valid,
    args=SFTConfig(dataset_text_field="text", max_seq_length=MAX_SEQ,
                   per_device_train_batch_size=2, gradient_accumulation_steps=4,
                   num_train_epochs=2, learning_rate=1e-5, logging_steps=10,
                   output_dir="adapters", report_to="none"),
)
trainer.train()
model.save_pretrained("adapters")
tokenizer.save_pretrained("adapters")
print("adapter written to adapters/ — see README.md for GGUF export")
'''

TRAIN_README = """# Fine-tuning this voice

Dataset: `train.jsonl` / `valid.jsonl` — chat format, one example per line:
system (conditioning) / user (source text) / assistant (authentic {voice}).
Rebuild any time with `revoice train prep {voice}` (flywheel pairs grow as you
review rewrites in the GUI; the de-voicing bootstrap needs a configured LLM).

## Apple Silicon (MLX)
    sh run_mlx.sh                 # mlx_lm.lora -> adapters/
    mlx_lm.server --model {base_model} --adapter-path adapters --port 8080
Then point revoice at it (revoice.yaml):
    rewriter: {{ kind: openai_compat, base_url: http://localhost:8080/v1, model: {voice}-lora }}

## CUDA (unsloth)
    python train_unsloth.py       # -> adapters/

## Archival export (GGUF — the durability floor)
Merge the adapter and convert, so the tuned voice runs forever via llama.cpp:
    mlx_lm.fuse --model {base_model} --adapter-path adapters --save-path merged/
    # then llama.cpp: python convert_hf_to_gguf.py merged/ --outfile {voice}.gguf
Store the .gguf in ../archive/ (inside the pack, gitignored like everything else).

## Evaluate before adopting
    revoice stats <output-of-tuned-model>.md --voice {voice}     # vs corpus self-band
    revoice judge <original>.md <rewritten>.md --voice {voice}   # rubric verdicts
The tuned model should beat your prompted baseline on both before it becomes the
default rewriter. Keep the critic a different model family.
"""


def write_tooling(pack: VoicePack, base_model: str) -> list[str]:
    tdir = pack.params_dir / "train"
    tdir.mkdir(parents=True, exist_ok=True)
    files = {
        "run_mlx.sh": MLX_SH.format(base_model=base_model),
        "train_unsloth.py": UNSLOTH_PY.format(base_model=base_model),
        "README.md": TRAIN_README.format(voice=pack.name, base_model=base_model),
    }
    for name, content in files.items():
        (tdir / name).write_text(content)
    return sorted(files)
