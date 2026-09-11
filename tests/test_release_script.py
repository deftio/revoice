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
        assert "working tree is not clean" in r.stderr
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
        assert "already exists" in r.stderr
    finally:
        if not existed:
            subprocess.run(["git", "tag", "-d", tag], cwd=ROOT, capture_output=True)


@bash
def test_the_retired_editing_flags_explain_what_replaced_them():
    for flag in ("--patch", "--minor", "--major", "--commit", "--push"):
        r = run(flag)
        assert r.returncode != 0
        assert "no longer edits the repo" in r.stderr, flag


def test_the_script_never_writes_to_the_repository():
    """The contract, read from the source: no redirect or in-place edit of tracked files."""
    import re

    src = SCRIPT.read_text()
    for pattern in (r"sed -i", r">\s*(?:revoice|pages|pyproject|CHANGELOG)",
                    r"\.write_text\(", r"git commit", r"git add"):
        assert not re.search(pattern, src), f"release.sh appears to write: {pattern}"


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
