"""CLI coverage via typer's CliRunner, stub providers, tmp cwd."""

import json
from types import SimpleNamespace

from typer.testing import CliRunner

from revoice.cli import app
from tests.conftest import TRAIN, build_learned_pack

runner = CliRunner()


def ok(result):
    assert result.exit_code == 0, result.output
    return result.output


def test_version():
    assert "revoice 0.1" in ok(runner.invoke(app, ["--version"]))


def test_help_topics():
    out = ok(runner.invoke(app, ["help"]))
    assert "workflow" in out
    out = ok(runner.invoke(app, ["help", "registers"]))
    assert "REGISTERS" in out
    r = runner.invoke(app, ["help", "nope"])
    assert r.exit_code == 1 and "unknown topic" in r.output


def test_voices_add_and_list(cwd):
    out = ok(runner.invoke(app, ["voices", "list"]))
    assert "no voices" in out
    out = ok(runner.invoke(app, ["voices", "add", "manu"]))
    assert "created" in out
    out = ok(runner.invoke(app, ["voices", "list"]))
    assert "manu" in out and "not_ready" in out
    out = ok(runner.invoke(app, ["list-voices"]))
    assert "manu" in out


def test_learn_verbose_and_quiet(cwd):
    ok(runner.invoke(app, ["voices", "add", "v"]))
    (cwd / "data" / "v" / "training-data" / "a.md").write_text(TRAIN.format(i=0))
    out = ok(runner.invoke(app, ["learn", "v"]))
    assert "a.md" in out and "readiness: prompts_ready" in out
    assert "style.yaml" in out and "rubrics.yaml" in out
    (cwd / "data" / "v" / "training-data" / "b.md").write_text(TRAIN.format(i=1))
    out = ok(runner.invoke(app, ["learn", "v", "--quiet"]))
    assert "b.md:" not in out


def test_status_and_missing_voice(learned_cwd):
    out = ok(runner.invoke(app, ["status", "t"]))
    assert json.loads(out)["name"] == "t"
    r = runner.invoke(app, ["status", "ghost"])
    assert r.exit_code == 1 and "not found" in r.output


def test_plan(learned_cwd):
    out = ok(runner.invoke(app, ["plan", "draft.md"]))
    assert json.loads(out)["doc_kind"]
    out = ok(runner.invoke(app, ["plan", "draft.md", "--voice", "t", "-r", "professional"]))
    assert json.loads(out)["target_register"] == "professional"
    (learned_cwd / "bad.xyz").write_text("x")
    r = runner.invoke(app, ["plan", "bad.xyz"])
    assert r.exit_code == 1 and "unsupported" in r.output


def test_stats_formats(learned_cwd):
    out = ok(runner.invoke(app, ["stats", "draft.md"]))
    assert "content blend" in out
    out = ok(runner.invoke(app, ["stats", "draft.md", "--voice", "t", "-r", "professional"]))
    assert "voice match" in out and "self-score" in out and "noisy" in out
    out = ok(runner.invoke(app, ["stats", "draft.md", "--json"]))
    assert json.loads(out)["fingerprint"]["words"] > 0
    out = ok(runner.invoke(app, ["stats", "draft.md", "-f", "md", "-v", "t"]))
    assert out.startswith("# revoice stats")
    out = ok(runner.invoke(app, ["stats", "draft.md", "-f", "html"]))
    assert "<html>" in out
    r = runner.invoke(app, ["stats", "draft.md", "-f", "bogus"])
    assert r.exit_code == 1 and "unknown format" in r.output
    # --output extension inference
    for name, marker in [("o.json", "{"), ("o.md", "# revoice"), ("o.html", "<html>")]:
        ok(runner.invoke(app, ["stats", "draft.md", "-o", name]))
        assert marker in (learned_cwd / name).read_text()
    # explicit format + output file
    ok(runner.invoke(app, ["stats", "draft.md", "-f", "md", "-o", "o2.txt"]))
    assert (learned_cwd / "o2.txt").read_text().startswith("# revoice")
    # unsupported input suffix
    (learned_cwd / "bad.xyz").write_text("x")
    r = runner.invoke(app, ["stats", "bad.xyz"])
    assert r.exit_code == 1 and "unsupported" in r.output


def test_stats_without_calibration(learned_cwd):
    (learned_cwd / "data" / "t" / "params" / "calibration.json").unlink()
    out = ok(runner.invoke(app, ["stats", "draft.md", "--voice", "t"]))
    assert "voice match" in out
    out = ok(runner.invoke(app, ["stats", "draft.md", "--voice", "t", "-f", "md"]))
    assert "—" in out
    ok(runner.invoke(app, ["stats", "draft.md", "--voice", "t", "-f", "html"]))


def test_run_variants(learned_cwd):
    out = ok(runner.invoke(app, ["run", "draft.md", "-o", "out.md", "--voice", "t"]))
    assert "out.md" in out and (learned_cwd / "out.md").is_file()
    assert (learned_cwd / "out.md.diff.json").is_file()
    # default output name + auto voice (single pack)
    ok(runner.invoke(app, ["run", "draft.md"]))
    assert (learned_cwd / "draft.revoiced.md").is_file()
    # raw
    out = ok(runner.invoke(app, ["run", "draft.md", "--raw"]))
    assert "3 MHz" in out
    # json (includes match_before/after)
    out = ok(runner.invoke(app, ["run", "draft.md", "--json"]))
    rec = json.loads(out)
    assert rec["match_before"] and rec["match_after"] and rec["spans"]
    # critique + cohesion + votes + register + strength 0
    ok(runner.invoke(app, ["run", "draft.md", "--critique", "--cohesion", "--votes", "2",
                           "-r", "professional", "-s", "0.0", "--quiet"]))
    # stdin
    out = ok(runner.invoke(app, ["run", "-", "-o", "fromstdin.md"], input="gotta note this maybe.\n"))
    assert (learned_cwd / "fromstdin.md").is_file()
    # stdin with default output name
    ok(runner.invoke(app, ["run", "-"], input="hello.\n"))
    assert (learned_cwd / "stdin.revoiced.md").is_file()


def test_run_errors(learned_cwd):
    (learned_cwd / "bad.xyz").write_text("x")
    r = runner.invoke(app, ["run", "bad.xyz"])
    assert r.exit_code == 1 and "only md/txt" in r.output
    r = runner.invoke(app, ["run", "draft.md", "--voice", "ghost"])
    assert r.exit_code == 1 and "not found" in r.output
    # ambiguous: two packs, no --voice
    build_learned_pack(learned_cwd / "data", "u")
    r = runner.invoke(app, ["run", "draft.md"])
    assert r.exit_code == 1 and "--voice required" in r.output


def test_judge(learned_cwd):
    (learned_cwd / "orig.md").write_text("The value is 42.")
    (learned_cwd / "new.md").write_text("The value equals 42.")
    out = ok(runner.invoke(app, ["judge", "orig.md", "new.md"]))
    assert "composite" in out
    out = ok(runner.invoke(app, ["judge", "orig.md", "new.md", "--voice", "t", "--json"]))
    assert json.loads(out)["rejected_by"] == []


def test_judge_rejected(learned_cwd, monkeypatch):
    import revoice.core.rubrics as rmod

    monkeypatch.setattr(rmod, "judge_all",
                        lambda *a, **k: {"composite": 0.1, "rejected_by": ["integrity"], "dimensions": {}})
    (learned_cwd / "orig.md").write_text("a")
    (learned_cwd / "new.md").write_text("b")
    out = ok(runner.invoke(app, ["judge", "orig.md", "new.md"]))
    assert "REJECTED by: integrity" in out


def test_doctor(cwd):
    out = ok(runner.invoke(app, ["doctor"]))
    assert "JSON parse: OK" in out
    (cwd / "revoice.yaml").write_text("data_dir: data\ncritic: {kind: bogus}\n")
    out = ok(runner.invoke(app, ["doctor"]))
    assert "FAILED" in out


def test_serve(cwd, monkeypatch):
    import threading
    import webbrowser

    import revoice.server as srv

    called = {}
    monkeypatch.setattr(srv, "serve", lambda cfg, host, port: called.update(host=host, port=port))
    out = ok(runner.invoke(app, ["serve", "--port", "7999"]))
    assert called["port"] == 7999 and "7999" in out

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(threading, "Timer",
                        lambda delay, fn: SimpleNamespace(start=fn))
    ok(runner.invoke(app, ["serve", "--gui"]))
    assert opened == ["http://127.0.0.1:7333"]
