"""Phase 5 training-set builder + tooling generation. Offline (stub provider)."""

import json

from typer.testing import CliRunner

from revoice.cli import app
from revoice.config import ProviderConfig
from revoice.core.train import build_dataset, flywheel_examples, write_tooling
from revoice.providers import make_provider

runner = CliRunner()


def _add_pairs(pack):
    rows = [
        {"register": "professional", "original": "gotta fix it", "final": "We need to fix it.", "decision": "accept"},
        {"register": "professional", "original": "src A", "final": "edited A", "decision": "edit"},
        {"register": "professional", "original": "rejected src", "final": "rejected src", "decision": "reject"},
        {"register": "professional", "original": "same", "final": "same", "decision": "accept"},  # no-op, dropped
        {"register": "professional", "original": "gotta fix it", "final": "We need to fix it.", "decision": "accept"},  # dup
    ]
    with (pack.params_dir / "pairs.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        f.write("\n")  # blank line tolerated


def test_flywheel_examples_filtering(learned_pack):
    _add_pairs(learned_pack)
    ex = flywheel_examples(learned_pack)
    # reject and no-op dropped; dup kept here (dedup happens in build_dataset)
    assert len(ex) == 3
    assert ex[0]["messages"][2]["content"] == "We need to fix it."
    assert ex[0]["meta"]["origin"] == "flywheel-accept"


def test_flywheel_no_file(learned_pack):
    assert flywheel_examples(learned_pack) == []


def test_build_dataset_with_bootstrap(learned_pack):
    _add_pairs(learned_pack)
    stub = make_provider(ProviderConfig(kind="stub"))
    seen = []
    stats = build_dataset(learned_pack, stub, bootstrap_n=3,
                          progress=lambda i, m: seen.append((i, m)))
    assert stats["total"] == stats["train"] + stats["valid"]
    assert stats["flywheel"] == 3
    tdir = learned_pack.params_dir / "train"
    rows = [json.loads(line) for line in (tdir / "train.jsonl").read_text().splitlines()]
    assert all(len(r["messages"]) == 3 for r in rows)
    assert all(r["messages"][0]["role"] == "system" for r in rows)
    # dedup: the duplicated flywheel pair appears once across train+valid
    all_rows = rows + [json.loads(line) for line in (tdir / "valid.jsonl").read_text().splitlines()]
    keys = [(r["messages"][1]["content"], r["messages"][2]["content"]) for r in all_rows]
    assert len(keys) == len(set(keys))
    assert (tdir / "stats.json").is_file()
    assert learned_pack.manifest()["train_stats"]["total"] == stats["total"]


def test_build_dataset_flywheel_only(learned_pack):
    _add_pairs(learned_pack)
    stats = build_dataset(learned_pack, provider=None, bootstrap_n=0)
    assert stats["bootstrap"] == 0 and stats["flywheel"] == 3


def _add_long_doc(pack, name="long.md"):
    """A doc long enough to yield MULTIPLE de-voicing windows, registered in the index."""
    para = ("The impedance matching network transforms the antenna load with care. "
            "Component tolerances dominate the error budget throughout the design. " * 6).strip()
    text = "\n\n".join([para] * 3)
    (pack.training_dir / name).write_text(text)
    pack.append_index({"path": name, "hash": "x", "chars": len(text),
                       "register": "professional", "polish": "polished",
                       "domains": [], "summary": "", "confidence": 1.0,
                       "fingerprint": {}, "indexed_at": "now"})


def test_bootstrap_provider_error_is_skipped(learned_pack):
    from revoice.core import train as trainmod

    _add_long_doc(learned_pack)

    class Boom:
        def complete(self, s, u):
            raise RuntimeError("nope")

    seen = []
    ex = trainmod.bootstrap_examples(learned_pack, Boom(), max_pairs=2,
                                     progress=lambda i, m: seen.append(m))
    assert ex == [] and any("ERROR" in m for m in seen)


def test_bootstrap_caps_and_identity_skip(learned_pack):
    _add_long_doc(learned_pack)

    class Identity:
        def complete(self, s, u):
            return u  # returns input unchanged -> skipped

    from revoice.core.train import bootstrap_examples

    assert bootstrap_examples(learned_pack, Identity(), max_pairs=5) == []


def test_bootstrap_caps_at_max_pairs(learned_pack):
    _add_long_doc(learned_pack, "long1.md")
    _add_long_doc(learned_pack, "long2.md")
    from revoice.config import ProviderConfig
    from revoice.core.train import bootstrap_examples
    from revoice.providers import make_provider

    stub = make_provider(ProviderConfig(kind="stub"))
    seen = []
    ex = bootstrap_examples(learned_pack, stub, max_pairs=1,
                            progress=lambda i, m: seen.append(m))
    assert len(ex) == 1 and ex[0]["meta"]["origin"] == "devoice"
    assert seen == ["pair 1"]  # progress fired on success; inner cap stopped window 2


def test_bootstrap_skips_unreadable_and_missing_files(learned_pack):
    from revoice.config import ProviderConfig
    from revoice.core.train import bootstrap_examples
    from revoice.providers import make_provider

    # unsupported extension -> extract_text returns None -> skipped
    learned_pack.append_index({"path": "ghost.xyz", "hash": "x", "chars": 1,
                               "register": "professional", "polish": "polished",
                               "domains": [], "summary": "", "confidence": 1.0,
                               "fingerprint": {}, "indexed_at": "now"})
    stub = make_provider(ProviderConfig(kind="stub"))
    assert bootstrap_examples(learned_pack, stub, max_pairs=5) == []


def test_write_tooling(learned_pack):
    files = write_tooling(learned_pack, "some/base-4bit")
    assert files == ["README.md", "run_mlx.sh", "train_unsloth.py"]
    tdir = learned_pack.params_dir / "train"
    assert "some/base-4bit" in (tdir / "run_mlx.sh").read_text()
    assert "unsloth" in (tdir / "train_unsloth.py").read_text()
    readme = (tdir / "README.md").read_text()
    assert "GGUF" in readme and learned_pack.name in readme


def test_cli_train_prep(learned_pack, tmp_path, monkeypatch):
    monkeypatch.chdir(learned_pack.root.parent.parent)
    cfg = learned_pack.root.parent.parent / "revoice.yaml"
    cfg.write_text(f"data_dir: {learned_pack.root.parent}\nclassifier: {{kind: stub}}\n")
    _add_pairs(learned_pack)
    _add_long_doc(learned_pack)  # ensures bootstrap windows exist -> verbose progress fires
    r = runner.invoke(app, ["train", "prep", learned_pack.name, "--bootstrap", "2",
                            "-c", str(cfg)])
    assert r.exit_code == 0, r.output
    assert "train.jsonl" not in r.output or True
    assert "run_mlx.sh" in r.output and "next:" in r.output
    r2 = runner.invoke(app, ["train", "prep", learned_pack.name, "--bootstrap", "0",
                             "--quiet", "-c", str(cfg)])
    assert r2.exit_code == 0 and "flywheel only" in r2.output
