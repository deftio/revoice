"""Privacy machinery: doctor's pack checks and the CI user-data gate."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from check_no_user_data import violations  # noqa: E402

from revoice.cli import app  # noqa: E402

runner = CliRunner()


def _cfg(tmp_path):
    f = tmp_path / "revoice.yaml"
    f.write_text(f"data_dir: {tmp_path / 'data'}\n")
    return f


def _mk_pack(tmp_path, name="me"):
    from revoice.core.voicepack import VoicePack

    return VoicePack.create(tmp_path / "data", name)


def test_doctor_privacy_protected(tmp_path, monkeypatch):
    _mk_pack(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    r = runner.invoke(app, ["doctor", "-c", str(_cfg(tmp_path))])
    assert "me: protected" in r.output


def test_doctor_privacy_not_ignored_warns(tmp_path, monkeypatch):
    _mk_pack(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    r = runner.invoke(app, ["doctor", "-c", str(_cfg(tmp_path))])
    assert "NOT ignored" in r.output


def test_doctor_privacy_missing_gitignore_and_no_git(tmp_path, monkeypatch):
    p = _mk_pack(tmp_path)
    (p.root / ".gitignore").unlink()

    def raise_fnf(*a, **k):
        raise FileNotFoundError("no git")

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    r = runner.invoke(app, ["doctor", "-c", str(_cfg(tmp_path))])
    assert "missing pack .gitignore" in r.output


def test_doctor_privacy_not_a_repo(tmp_path, monkeypatch):
    _mk_pack(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=128))
    r = runner.invoke(app, ["doctor", "-c", str(_cfg(tmp_path))])
    assert "me: protected" in r.output


def test_doctor_privacy_no_packs(tmp_path):
    (tmp_path / "data").mkdir()
    r = runner.invoke(app, ["doctor", "-c", str(_cfg(tmp_path))])
    assert "no voice packs found" in r.output


def test_gate_clean_paths_pass():
    ok = ["README.md", "revoice/cli.py", "examples/voices/twain/training-data/a.md",
          "revoice.example.yaml", "tests/test_pipeline.py", "docs/demo/voices.json"]
    assert violations(ok) == []


def test_gate_catches_each_rule():
    cases = {
        "data/manu/training-data/secret.md": "data/",
        "somewhere/params/pairs.jsonl": "/params/",
        "backup/training-data/notes.md": "training-data",
        "pairs.jsonl": "voice-pack artifact",
        "revoice.yaml": "local config",
    }
    for path, needle in cases.items():
        bad = violations([path])
        assert bad and needle in bad[0][1] or needle in bad[0][0], (path, bad)


def test_gate_examples_and_tests_exempt():
    assert violations(["examples/voices/darwin/training-data/x.md"]) == []
    assert violations(["tests/pairs.jsonl"]) == []


def test_gate_env_files_and_secrets():
    from check_no_user_data import secret_violations

    bad = secret_violations([".env"]) + secret_violations(["deploy/id_rsa"])
    assert len(bad) == 2 and all("env/credential" in b[1] for b in bad)


def test_gate_secret_patterns_in_content(tmp_path, monkeypatch):
    from check_no_user_data import secret_violations

    monkeypatch.chdir(tmp_path)
    hot = tmp_path / "config.py"
    hot.write_text('KEY = "sk-ant-' + "a1B2" * 8 + '"\n')  # gate: allow-secret
    ok = tmp_path / "readme.md"
    ok.write_text("set ANTHROPIC_API_KEY and OPENROUTER_API_KEY in your env\n")
    allowed = tmp_path / "test_fake.py"
    allowed.write_text('FAKE = "sk-ant-' + "x" * 32 + '"  # gate: allow-secret\n')
    binary = tmp_path / "img.dat"
    binary.write_bytes(b"\x00\x01\x02sk-ant-" + b"y" * 40)
    bad = secret_violations(["config.py", "readme.md", "test_fake.py", "img.dat", "missing.txt"])
    assert len(bad) == 1 and "anthropic" in bad[0][1] and bad[0][0].startswith("config.py:")
