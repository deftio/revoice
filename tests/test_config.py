"""Config search order: explicit, $REVOICE_CONFIG, ./revoice.yaml, home fallback, default."""

from pathlib import Path

from revoice.config import load_config


def test_explicit_relative_data_dir(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("data_dir: mydata\n")
    cfg = load_config(cfg_file)
    assert cfg.data_dir == (tmp_path / "mydata").resolve()


def test_explicit_absolute_data_dir(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(f"data_dir: {tmp_path / 'abs'}\n")
    assert load_config(cfg_file).data_dir == tmp_path / "abs"


def test_env_var(tmp_path, monkeypatch):
    cfg_file = tmp_path / "env.yaml"
    cfg_file.write_text("data_dir: d\nrewriter:\n  kind: stub\n")
    monkeypatch.setenv("REVOICE_CONFIG", str(cfg_file))
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.data_dir == (tmp_path / "d").resolve()
    assert cfg.rewriter.kind == "stub"


def test_cwd_file(tmp_path, monkeypatch):
    monkeypatch.delenv("REVOICE_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "revoice.yaml").write_text("")  # empty yaml -> {} -> defaults
    cfg = load_config()
    assert cfg.data_dir == (tmp_path / "data").resolve()


def test_home_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("REVOICE_CONFIG", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    home = tmp_path / "home"
    (home / ".config" / "revoice").mkdir(parents=True)
    (home / ".config" / "revoice" / "config.yaml").write_text("data_dir: homedata\n")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    cfg = load_config()
    assert cfg.data_dir == (home / ".config" / "revoice" / "homedata").resolve()


def test_no_config_default(tmp_path, monkeypatch):
    monkeypatch.delenv("REVOICE_CONFIG", raising=False)
    empty = tmp_path / "empty2"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    cfg = load_config()
    assert cfg.data_dir == Path("data")
    assert cfg.classifier.kind == "stub"
