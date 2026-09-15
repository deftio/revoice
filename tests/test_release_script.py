"""The release script's guards and its read-only contract.

Only the cheap, early stages are exercised here. The script runs the full test suite as
one of its own gates, so a test that drove it past that point would recurse into pytest.

The central property is that the script writes NOTHING to the repository — it ships what
is already committed. If a release edits code, what ships is not what was reviewed and
tested, and the commit CI validated is not the commit that gets tagged.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "release.sh"

bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def run(*args, **kw):
    return subprocess.run([str(SCRIPT), *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=180, env={**kw.pop("env", {}), "NO_COLOR": "1",
                                                       "PATH": __import__("os").environ["PATH"],
                                                       "HOME": __import__("os").environ["HOME"]})


@bash
def test_script_is_executable_and_valid_bash():
    assert SCRIPT.stat().st_mode & 0o111, "release.sh is not executable"
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@bash
def test_help_documents_the_ladder_and_the_read_only_contract():
    r = run("--help")
    assert r.returncode == 0
    for flag in ("--pr", "--release", "--pypi", "--expect", "--yes"):
        assert flag in r.stdout, f"--help does not mention {flag}"
    assert "writes nothing to the repository" in r.stdout


@bash
def test_refuses_a_dirty_working_tree():
    """Release ships what is committed. An uncommitted change is one CI never saw."""
    scratch = ROOT / "release-dirty-probe.tmp"
    scratch.write_text("uncommitted\n")
    try:
        r = run()
        assert r.returncode != 0
        assert "uncommitted changes" in r.stderr
        # and it must say what to type, not merely what is wrong
        assert "git add -A && git commit" in r.stderr
        assert "git stash -u" in r.stderr
        assert "release-dirty-probe.tmp" in r.stderr, "it should list the offending files"
    finally:
        scratch.unlink()


@bash
def test_rejects_an_unknown_option():
    r = run("--unleash-the-hounds")
    assert r.returncode != 0
    assert "unknown option" in r.stderr


@bash
def test_expect_guards_against_releasing_the_wrong_version():
    r = run("--expect", "99.99.99")
    assert r.returncode != 0
    assert "--expect said 99.99.99" in r.stderr


@bash
def test_refuses_to_reuse_an_existing_tag():
    import revoice

    tag = f"v{revoice.__version__}"
    existed = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                             cwd=ROOT, capture_output=True).returncode == 0
    if not existed:
        subprocess.run(["git", "tag", tag], cwd=ROOT, capture_output=True)
    try:
        r = run()
        assert r.returncode != 0
        assert "already tagged" in r.stderr
        # the next version is computed for you, not left as an exercise
        major, minor, patch = revoice.__version__.split(".")
        nxt = f"{major}.{minor}.{int(patch) + 1}"
        assert nxt in r.stderr, f"should suggest {nxt}"
        assert "revoice/__init__.py" in r.stderr and "CHANGELOG.md" in r.stderr
    finally:
        if not existed:
            subprocess.run(["git", "tag", "-d", tag], cwd=ROOT, capture_output=True)


@bash
def test_the_retired_editing_flags_explain_what_replaced_them():
    for flag in ("--patch", "--minor", "--major", "--commit", "--push"):
        r = run(flag)
        assert r.returncode != 0
        assert "no longer edits the repo" in r.stderr, flag


def _executable_source() -> str:
    """The script with double-quoted strings removed, leaving only what bash would RUN.

    The script's failure messages quote the commands you should type — `git commit -am`,
    `sed -i '' 's/.../.../'` — because telling someone what is wrong without telling them
    what to type is half a message. Those live inside double-quoted arguments to `need`
    and `die`. A real write would not: `sed -i` as a command is unquoted. Stripping
    double-quoted spans keeps the distinction exact, and keeps the guard below honest
    rather than merely strict.
    """
    import re

    return re.sub(r'"(?:[^"\\]|\\.)*"', '""', SCRIPT.read_text(), flags=re.S)


def test_the_script_never_writes_to_the_repository():
    """The contract, read from the source: no redirect or in-place edit of tracked files."""
    import re

    src = _executable_source()
    for pattern in (r"sed -i", r">\s*(?:revoice|pages|pyproject|CHANGELOG)",
                    r"\.write_text\(", r"git commit", r"git add"):
        assert not re.search(pattern, src), f"release.sh appears to write: {pattern}"


def test_the_guard_would_still_catch_a_real_write():
    """The stripping above must not defang the test it protects."""
    import re

    assert re.search(r"git commit", 'git commit -am "Release"')
    # quoted-as-instruction is ignored, bare-as-command is not
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', 'need "run: git commit -am x"', flags=re.S)
    assert not re.search(r"git commit", stripped)
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', 'git commit -am "Release $V"', flags=re.S)
    assert re.search(r"git commit", stripped)


def test_the_version_is_read_from_the_single_source_of_truth():
    src = SCRIPT.read_text()
    assert "revoice/__init__.py" in src
    assert "__version__" in src
    # and it must not parse a version out of pyproject, which merely derives one
    assert 'pyproject.toml").read_text()' not in src


# ---------- the script's own promises, read from its source ----------


def test_the_ladder_gates_each_step_behind_its_own_flag():
    """Nothing reaches the remote without --pr; nothing merges or publishes without
    --release; nothing reaches PyPI without --pypi."""
    src = SCRIPT.read_text()
    for gate in ('if [ "$DO_PR" -eq 0 ]', 'if [ "$DO_RELEASE" -eq 0 ]',
                 'if [ "$DO_PYPI" -eq 1 ]'):
        assert gate in src, f"missing gate: {gate}"
    assert src.count("exit 0") >= 3
    assert src.count("confirm ") >= 3, "push, merge and publish must each confirm"


def test_pypi_upload_is_opt_in_and_checks_for_a_token():
    src = SCRIPT.read_text()
    assert "uv publish" in src
    assert "UV_PUBLISH_TOKEN" in src
    assert src.index("UV_PUBLISH_TOKEN") < src.index("uv publish"), \
        "the token check must come before the upload"
    assert "cannot be re-uploaded" in src, "an irreversible upload should say so"


def test_generated_site_files_are_verified_not_regenerated():
    """Regenerating during a release would mean the release authors code."""
    src = SCRIPT.read_text()
    assert "export_demo_baselines.py --check" in src
    assert "export_demo_baselines.py\n" not in src.replace(" --check", " --check\n")


def test_release_is_gated_on_remote_ci_not_local_checks():
    """The local gates are a fast filter; CI on the PR is what decides."""
    src = SCRIPT.read_text()
    assert "gh pr checks" in src and "--watch" in src, "must block on the real CI run"
    assert "--fail-fast" in src
    # the merge must come after the CI wait, not before it
    assert src.index("gh pr checks") < src.index("gh pr merge")
    assert src.index("gh pr checks") < src.index("gh release create")


def test_the_flow_uses_a_pull_request_and_a_squash_merge():
    src = SCRIPT.read_text()
    assert "gh pr create" in src, "main should only move through a reviewed PR"
    assert "gh pr merge" in src and "--squash" in src
    assert "--base" in src and "$MAIN_BRANCH" in src


def test_a_github_release_is_published_with_the_built_artefacts():
    """'Built all targets' is only worth anything if the targets are what ships."""
    src = SCRIPT.read_text()
    assert "gh release create" in src
    assert "--notes-file" in src, "release notes should come from the CHANGELOG"
    assert ".whl" in src.split("gh release create")[1].split("\n\n")[0]
    assert ".tar.gz" in src.split("gh release create")[1].split("\n\n")[0]


def test_gh_is_required_and_checked_for_auth_before_any_remote_step():
    src = SCRIPT.read_text()
    assert "gh auth status" in src
    assert src.index("gh auth status") < src.index("gh pr create")


def test_the_verify_stage_runs_the_same_gates_as_ci():
    src = SCRIPT.read_text()
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for gate in ("check_no_user_data.py", "ruff check", "--cov-fail-under=100", "revoice bench"):
        assert gate in src, f"release skips a gate CI enforces: {gate}"
        assert gate in ci, f"CI no longer runs {gate}; release.sh is now stricter than CI"


def test_the_release_builds_both_distribution_targets():
    src = SCRIPT.read_text()
    assert "uv build" in src
    assert "tar.gz" in src and ".whl" in src, "must verify BOTH sdist and wheel exist"
    assert "uv pip install" in src, "a built wheel that cannot install is not a release"


# ---------------------------------------------------------------------------------
# Actionability.
#
# A gate that fails should hand back the command, not just the diagnosis — and if three
# gates fail it should say so once rather than making you find them one run at a time.
# These are the tests for that, because "the error message is helpful" decays silently.

@bash
def test_every_problem_is_reported_in_one_pass():
    """Three simultaneous problems, one run, three numbered items."""
    import re

    import revoice

    changelog = ROOT / "CHANGELOG.md"
    original = changelog.read_text()
    scratch = ROOT / "release-multi-probe.tmp"
    tag = f"v{revoice.__version__}"
    tag_existed = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                                 cwd=ROOT, capture_output=True).returncode == 0
    try:
        changelog.write_text(re.sub(rf"^## {re.escape(revoice.__version__)} .*$",
                                    f"## {revoice.__version__} (unreleased)",
                                    original, count=1, flags=re.M))
        scratch.write_text("uncommitted\n")
        if not tag_existed:
            subprocess.run(["git", "tag", tag], cwd=ROOT, capture_output=True)

        r = run()
        assert r.returncode != 0
        assert "not ready to release" in r.stderr
        assert "3 things to do first" in r.stderr, r.stderr
        for n in ("1.", "2.", "3."):
            assert f"\n{n} " in r.stderr or r.stderr.startswith(f"{n} "), n
        # ordering matters: fixing the tag changes the version the others refer to
        assert "do them in order" in r.stderr
        assert "then re-run:" in r.stderr
    finally:
        changelog.write_text(original)
        scratch.unlink(missing_ok=True)
        if not tag_existed:
            subprocess.run(["git", "tag", "-d", tag], cwd=ROOT, capture_output=True)


@bash
def test_an_undated_changelog_hands_back_the_exact_edit():
    import re
    from datetime import datetime, timezone

    import revoice

    changelog = ROOT / "CHANGELOG.md"
    original = changelog.read_text()
    v = revoice.__version__
    try:
        changelog.write_text(re.sub(rf"^## {re.escape(v)} .*$", f"## {v} (unreleased)",
                                    original, count=1, flags=re.M))
        r = run()
        assert r.returncode != 0
        assert "(unreleased)" in r.stderr
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # a runnable line, with today's date already substituted in
        assert f"## {v} - {today}" in r.stderr
        assert "sed -i" in r.stderr and "CHANGELOG.md" in r.stderr
        # BSD sed needs the empty arg, GNU sed refuses it. The script must suggest the
        # one that is actually installed — wrong advice is worse than none.
        import subprocess as sp
        gnu = sp.run(["sed", "--version"], capture_output=True).returncode == 0
        suggested = next(line for line in r.stderr.splitlines() if "sed -i" in line)
        if gnu:
            assert "sed -i ''" not in suggested, f"GNU sed given BSD syntax: {suggested}"
        else:
            assert "sed -i ''" in suggested, f"BSD sed given GNU syntax: {suggested}"
    finally:
        changelog.write_text(original)


@bash
def test_no_message_merely_states_the_problem():
    """Every `need` in the script carries something runnable.

    A message that says what is wrong and not what to type is half a message, and this is
    the check that keeps the next one from being written that way.
    """
    import re

    src = SCRIPT.read_text()
    calls = re.findall(r'\bneed\s+"(.*?)"\s*\\?\n(.*?)(?=\n\s*(?:else|fi|;;|\bneed\b|$))',
                       src, re.S)
    assert calls, "no need() calls found — has the script been restructured?"
    runnable = ("git ", "uv ", "python ", "sed ", "$EDITOR", "gh ", "brew ", "export ")
    for what, body in calls:
        assert any(tok in body for tok in runnable), (
            f"the message {what!r} tells you what is wrong but not what to type")


@bash
def test_a_failing_gate_names_the_command_that_reproduces_it():
    """The verify stage runs with --quiet; a failure must say how to see the output."""
    src = SCRIPT.read_text()
    assert "Reproduce it:" in src
    # the suggested commands must NOT be the quiet ones, or you re-run and see nothing
    for line in src.splitlines():
        if line.strip().startswith('"uv run') and "Reproduce" not in line:
            assert "--quiet" not in line, f"reproduce command is silenced: {line.strip()}"


@bash
def test_missing_tools_say_how_to_install_them():
    src = SCRIPT.read_text()
    assert "astral.sh/uv/install.sh" in src or "brew install uv" in src
    assert "gh auth login" in src
    assert "brew install gh" in src


def _ci_like_checkout(tmp: Path) -> Path:
    """A standalone repo shaped like `actions/checkout` on a pull_request.

    Detached HEAD, NO branches, NO remotes. A `git worktree` is not good enough and
    getting that wrong cost a CI round trip: a worktree shares the parent repository's
    refs, so origin/main is visible inside it and a fix that depends on origin/main
    passes there while still failing in CI.
    """
    import subprocess as sp

    wt = tmp / "ci-like"
    wt.mkdir()
    def run_git(*a):
        return sp.run(["git", *a], cwd=wt, capture_output=True, text=True)

    sp.run(["git", "init", "-q", "-b", "tmpbranch", str(wt)], capture_output=True)
    run_git("config", "user.email", "t@example.com")
    run_git("config", "user.name", "t")
    for rel in ("scripts", "revoice", "tests", "pages"):
        (wt / rel).mkdir(parents=True, exist_ok=True)
    (wt / "scripts" / "release.sh").write_bytes(SCRIPT.read_bytes())
    (wt / "scripts" / "release.sh").chmod(0o755)
    (wt / "revoice" / "__init__.py").write_text('__version__ = "9.9.9"\n')
    (wt / "CHANGELOG.md").write_text("# Changelog\n\n## 9.9.9 (unreleased)\n\nnotes\n")
    run_git("add", "-A")
    run_git("commit", "-qm", "init")
    run_git("checkout", "-q", "--detach")
    run_git("branch", "-D", "tmpbranch")
    return wt


@bash
def test_it_works_in_a_ci_style_detached_checkout():
    """The verify path must run with no branches and no remotes — that is what CI has.

    Requiring a main branch here made the script die in preflight in CI, before reaching
    a single gate, and took five of the tests above with it.
    """
    import subprocess as sp
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        wt = _ci_like_checkout(Path(tmp))
        # `git branch` prints a "(HEAD detached at ...)" pseudo-entry even with --format,
        # so count real refs instead — that is what "no branches" has to mean here.
        refs = sp.run(["git", "for-each-ref", "--format=%(refname)", "refs/heads/"],
                      cwd=wt, capture_output=True, text=True).stdout.strip()
        assert refs == "", f"the fixture should have no branches, has: {refs}"
        assert sp.run(["git", "remote"], cwd=wt, capture_output=True,
                      text=True).stdout.strip() == "", "the fixture should have no remotes"

        env = {"NO_COLOR": "1", "PATH": __import__("os").environ["PATH"],
               "HOME": __import__("os").environ["HOME"]}
        r = sp.run([str(wt / "scripts" / "release.sh")], cwd=wt, env=env,
                   capture_output=True, text=True, timeout=180)
        combined = r.stdout + r.stderr
        # it must reach the GATES, not die on the branch check
        assert "branch here" not in combined, combined[:400]
        assert "(unreleased)" in combined, f"never reached the changelog gate:\n{combined[:400]}"


@bash
def test_publishing_from_a_ci_style_checkout_is_refused_with_the_fix():
    """Verifying does not need a branch; publishing does, and says so."""
    import subprocess as sp
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        wt = _ci_like_checkout(Path(tmp))
        env = {"NO_COLOR": "1", "PATH": __import__("os").environ["PATH"],
               "HOME": __import__("os").environ["HOME"]}
        r = sp.run([str(wt / "scripts" / "release.sh"), "--pr"], cwd=wt, env=env,
                   capture_output=True, text=True, timeout=180)
        assert r.returncode != 0
        # --pr checks for gh BEFORE preflight, and CI runners have gh installed but not
        # authenticated. Either refusal is correct; both must name a command. Asserting
        # only the branch message would fail in CI for a reason that is not a bug.
        if "gh is installed but not authenticated" in r.stderr or "gh (GitHub CLI) not found" in r.stderr:
            assert "gh auth login" in r.stderr
        else:
            assert "HEAD is detached" in r.stderr or "no 'main' branch" in r.stderr
            assert "git checkout" in r.stderr or "git fetch" in r.stderr
