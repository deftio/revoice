"""The release script's guards.

Only the cheap, early stages are exercised here. The script runs the full test suite as
one of its own gates, so a test that drove it past that point would recurse into pytest
— every guard below fails before the script reaches that stage, which is itself part of
the design: nothing expensive runs until the cheap checks have passed, and nothing is
written to the working tree until they have.
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
def test_help_documents_the_safety_ladder():
    r = run("--help")
    assert r.returncode == 0
    for flag in ("--patch", "--commit", "--pr", "--release", "--yes", "--version"):
        assert flag in r.stdout, f"--help does not mention {flag}"
    assert "Nothing before --pr touches the remote" in r.stdout


@bash
def test_refuses_without_a_version_choice():
    r = run()
    assert r.returncode != 0
    assert "say which version" in r.stderr


@bash
def test_rejects_an_unknown_option():
    r = run("--unleash-the-hounds")
    assert r.returncode != 0
    assert "unknown option" in r.stderr


@bash
def test_refuses_a_version_the_changelog_has_no_notes_for():
    """Releasing without notes is the easiest mistake to make and the least visible."""
    r = run("--version", "99.99.99")
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "CHANGELOG" in out and "99.99.99" in out


@bash
def test_refuses_to_reuse_an_existing_tag():
    tag = "v0.0.99-release-test"
    subprocess.run(["git", "tag", tag], cwd=ROOT, capture_output=True)
    try:
        r = run("--version", "0.0.99-release-test")
        assert r.returncode != 0
    finally:
        subprocess.run(["git", "tag", "-d", tag], cwd=ROOT, capture_output=True)


@bash
def test_a_failed_run_leaves_the_working_tree_untouched():
    """The changelog gate runs BEFORE anything is written, on purpose."""
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            capture_output=True, text=True).stdout
    run("--version", "99.99.99")
    after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True).stdout
    assert before == after, "a failed release run modified the working tree"


# ---------- the script's own promises, read from its source ----------


def test_the_ladder_gates_each_step_behind_its_own_flag():
    """Nothing reaches the remote without --pr; nothing merges or publishes without
    --release. Each rung exits early rather than falling through to the next."""
    src = SCRIPT.read_text()
    assert 'if [ "$DO_COMMIT" -eq 0 ]' in src and 'if [ "$DO_PR" -eq 0 ]' in src \
        and 'if [ "$DO_RELEASE" -eq 0 ]' in src
    # each early-exit block ends the run rather than continuing
    assert src.count("exit 0") >= 4
    assert src.count("confirm ") >= 4, "branch, push, merge and publish must each confirm"


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


def test_the_retired_push_flag_says_what_replaced_it():
    src = SCRIPT.read_text()
    assert "--push is now --pr" in src


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
