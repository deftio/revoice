#!/usr/bin/env bash
#
# revoice release: ship what is already committed.
#
# This script writes nothing to the repository. It does not bump the version, edit the
# changelog, or regenerate anything — it verifies, builds, and publishes. Preparing a
# release is normal work you do and commit; releasing is mechanical and separate.
#
#   1. bump revoice/__init__.py          <- the single source of truth for the version
#   2. write the CHANGELOG section
#   3. python scripts/export_demo_baselines.py    (the site embeds the version)
#   4. commit
#   5. ./scripts/release.sh --release
#
# Why the split: if the release edits code, what ships is not what was reviewed and
# tested. Read-only means the commit CI validates is byte-for-byte the commit that gets
# tagged and published.
#
#   ./scripts/release.sh            verify, test, build — report readiness, touch nothing
#   ./scripts/release.sh --pr       push the branch and open a PR into main
#   ./scripts/release.sh --release  wait for CI green, squash-merge, tag, publish
#
# The local checks are a fast filter, not the authority. --release blocks on the CI run
# GitHub performs against the PR and refuses to merge or publish if it is red: a release
# whose only evidence is "it passed on my laptop" is what this exists to prevent.
#
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# ---------------------------------------------------------------- output helpers ----
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'
  YLW=$'\033[33m'; RST=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; RST=""
fi
step()  { printf "\n%s==> %s%s\n" "$BOLD" "$1" "$RST"; }
ok()    { printf "    %s✓%s %s\n" "$GRN" "$RST" "$1"; }
note()  { printf "    %s%s%s\n" "$DIM" "$1" "$RST"; }
warn()  { printf "    %s!%s %s\n" "$YLW" "$RST" "$1"; }
die()   { printf "\n%serror:%s %s\n" "$RED" "$RST" "$1" >&2; exit 1; }

# ---------------------------------------------------------------------- options ----
DO_PR=0; DO_RELEASE=0; DO_PYPI=0; ASSUME_YES=0
MAIN_BRANCH="main"; CI_TIMEOUT=1800; EXPECT=""
usage() {
  sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'USAGE'
Options:
  --pr                 push the branch and open a PR into main
  --release            wait for CI, squash-merge, tag, publish a GitHub Release
                       (implies --pr)
  --pypi               also publish to PyPI (needs UV_PUBLISH_TOKEN); off by default
  --expect X.Y.Z       fail unless the committed version is exactly this
  --yes                do not prompt
  --main-branch NAME   target branch, default "main"
  --ci-timeout SECONDS how long to wait for CI, default 1800
  -h, --help           this text
USAGE
}
while [ $# -gt 0 ]; do
  case "$1" in
    --pr) DO_PR=1 ;;
    --release) DO_RELEASE=1; DO_PR=1 ;;
    --pypi) DO_PYPI=1 ;;
    --expect) EXPECT="${2:-}"; shift ;;
    --yes|-y) ASSUME_YES=1 ;;
    --main-branch) MAIN_BRANCH="${2:-main}"; shift ;;
    --ci-timeout) CI_TIMEOUT="${2:-1800}"; shift ;;
    --patch|--minor|--major|--version|--commit|--push)
      die "$1 is gone: this script no longer edits the repo.
       Bump revoice/__init__.py, write the CHANGELOG, run
       'python scripts/export_demo_baselines.py', commit, then re-run." ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1  (try --help)" ;;
  esac
  shift
done

confirm() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  printf "\n%s%s%s [y/N] " "$BOLD" "$1" "$RST"
  read -r reply </dev/tty || true
  case "$reply" in [yY]*) return 0 ;; *) die "stopped at your request — nothing was changed" ;; esac
}

PY=$(command -v python3 || true)
[ -n "$PY" ] || die "python3 not found"
command -v uv >/dev/null || die "uv not found — needed to build and to make a clean test env"
command -v node >/dev/null || warn "node not found: the JS/Python parity tests will SKIP, which is how the site and the tool drift apart"
if [ "$DO_PR" -eq 1 ]; then
  command -v gh >/dev/null || die "gh (GitHub CLI) not found — see https://cli.github.com"
  gh auth status >/dev/null 2>&1 || die "gh is not authenticated — run: gh auth login"
fi

# ------------------------------------------------------ 1. what are we releasing? ----
step "Preflight"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git rev-parse --verify "$MAIN_BRANCH" >/dev/null 2>&1 || die "no '$MAIN_BRANCH' branch here"

# The version is READ, never written. revoice/__init__.py is the single source of truth;
# pyproject.toml derives from it and the site is generated from it.
VERSION=$("$PY" - <<'PYEOF'
import pathlib, re, sys
m = re.search(r'^__version__ = "([^"]+)"',
              pathlib.Path("revoice/__init__.py").read_text(), re.M)
if not m:
    sys.exit("revoice/__init__.py has no __version__")
print(m.group(1))
PYEOF
)
note "version   $VERSION   (from revoice/__init__.py)"
note "branch    $BRANCH -> $MAIN_BRANCH"
[ -z "$EXPECT" ] || [ "$EXPECT" = "$VERSION" ] \
  || die "committed version is $VERSION, but --expect said $EXPECT"

# Tag first: it is the cheapest check and its message is the more useful one. A tag that
# already exists means the release is not ready at all, which is worth knowing before
# being told to tidy the working tree.
git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null \
  && die "tag v$VERSION already exists — bump revoice/__init__.py for a new release"
ok "tag v$VERSION is free"

# Release ships what is committed. An uncommitted change is a change CI never saw.
if [ -n "$(git status --porcelain)" ]; then
  git status --short | sed 's/^/      /'
  die "working tree is not clean.
       This script ships what is committed — commit or stash first, so the artefacts
       are built from exactly the tree CI will test."
fi
ok "working tree clean"

# ---------------------------------------------------------- 2. consistency checks ----
step "Consistency"
"$PY" - "$VERSION" <<'PYEOF' || exit 1
import pathlib, re, sys
v = sys.argv[1]
text = pathlib.Path("CHANGELOG.md").read_text()
m = re.search(rf'^## {re.escape(v)}\b(.*)$', text, re.M)
if not m:
    print(f"    CHANGELOG.md has no '## {v}' section — write the notes before releasing")
    raise SystemExit(1)
if "(unreleased)" in m.group(1):
    print(f"    '## {v}' is still marked (unreleased) — date it before shipping")
    raise SystemExit(1)
body = text[m.end():]
nxt = re.search(r'^## ', body, re.M)
entry = (body[:nxt.start()] if nxt else body).strip()
if len(entry) < 40:
    print(f"    the '## {v}' section is empty — a release with no notes helps nobody")
    raise SystemExit(1)
PYEOF
ok "CHANGELOG has dated notes for $VERSION"

DERIVED=$(uv run --quiet python -c 'import revoice; print(revoice.__version__)')
[ "$DERIVED" = "$VERSION" ] || die "the package reports $DERIVED, the source says $VERSION"
ok "runtime and packaging agree on $VERSION"

uv run --quiet python scripts/export_demo_baselines.py --check \
  || die "the site's generated files are stale — regenerate and commit them"
ok "pages/version.js, population.json and voices.json are current"

# ------------------------------------------------------------------- 3. test (CI) ----
step "Test (the same gates CI runs)"
uv run --quiet python scripts/check_no_user_data.py >/dev/null && ok "privacy gate"
uv run --quiet ruff check revoice/ tests/ scripts/ >/dev/null && ok "ruff, zero warnings"
uv run --quiet pytest tests/ -q --cov=revoice --cov-fail-under=100 >/dev/null \
  && ok "tests pass at 100% coverage"
uv run --quiet revoice bench examples/voices --lengths 50,200 -n 10 --no-content-control >/dev/null \
  && ok "voice-metric bench runs clean"

# -------------------------------------------------------------------- 4. build all ----
step "Build"
rm -rf dist
uv build >/dev/null 2>&1 || die "build failed (run 'uv build' to see why)"
[ -f dist/revoice-"$VERSION".tar.gz ] || die "sdist for $VERSION not produced"
ls dist/revoice-"$VERSION"-*.whl >/dev/null 2>&1 || die "wheel for $VERSION not produced"
ls dist | sed 's/^/      /'

# Install the wheel somewhere clean: the only check that catches a package which builds
# fine and is broken on arrival — a missing package-data entry, a bad manifest.
VERIFY_ENV=$(mktemp -d)
trap 'rm -rf "$VERIFY_ENV"' EXIT
uv venv --quiet "$VERIFY_ENV/venv" >/dev/null 2>&1
uv pip install --quiet --python "$VERIFY_ENV/venv/bin/python" dist/revoice-"$VERSION"-*.whl
INSTALLED=$("$VERIFY_ENV/venv/bin/revoice" --version | awk '{print $NF}')
[ "$INSTALLED" = "$VERSION" ] || die "installed wheel reports '$INSTALLED', expected '$VERSION'"
"$VERIFY_ENV/venv/bin/python" - <<'PYEOF' || die "the built wheel is missing package data"
import importlib.resources as r
for name in ("rubric/README.md", "voicemetric/README.md", "static/index.html"):
    pkg, _, rest = name.partition("/")
    assert (r.files("revoice") / pkg / rest).is_file(), f"missing from wheel: {name}"
PYEOF
ok "wheel installs cleanly, reports $VERSION, carries its package data"

# ---------------------------------------------------------------------- 5. summary ----
NOTES=$(sed -n "/^## $VERSION/,/^## /p" CHANGELOG.md | sed '1d;$d')
if [ "$DO_PR" -eq 0 ]; then
  step "Ready"
  note "version     $VERSION"
  note "artefacts   $(ls dist | tr '\n' ' ')"
  note "commit      $(git rev-parse --short HEAD) on $BRANCH"
  cat <<EOF

  ${BOLD}Nothing was changed, pushed or published.${RST}

  Next:
      ./scripts/release.sh --pr        # push this branch and open a PR
      ./scripts/release.sh --release   # ...and merge + publish once CI is green
EOF
  exit 0
fi

# ------------------------------------------------------------------ 6. push and PR ----
step "Pull request"
RELEASE_BRANCH="$BRANCH"
if [ "$BRANCH" = "$MAIN_BRANCH" ]; then
  # main only ever moves through a reviewed, CI-checked squash merge, so give this commit
  # a branch to be reviewed on. No commit is created; the branch just points at HEAD.
  RELEASE_BRANCH="release/v$VERSION"
  git rev-parse -q --verify "$RELEASE_BRANCH" >/dev/null || git branch "$RELEASE_BRANCH"
  git checkout -q "$RELEASE_BRANCH"
  note "branched $RELEASE_BRANCH at $(git rev-parse --short HEAD)"
fi
confirm "Push '$RELEASE_BRANCH' and open a PR into $MAIN_BRANCH for $VERSION?"
git push -q --set-upstream origin "$RELEASE_BRANCH"
ok "pushed $RELEASE_BRANCH"

PR_URL=$(gh pr view "$RELEASE_BRANCH" --json url -q .url 2>/dev/null || true)
if [ -z "$PR_URL" ]; then
  PR_BODY=$(printf '%s\n\n---\nOpened by scripts/release.sh. Merging is gated on CI.\n' "$NOTES")
  PR_URL=$(gh pr create --base "$MAIN_BRANCH" --head "$RELEASE_BRANCH" \
    --title "Release $VERSION" --body "$PR_BODY")
  ok "opened $PR_URL"
else
  note "PR already open: $PR_URL"
fi

if [ "$DO_RELEASE" -eq 0 ]; then
  cat <<EOF

  ${BOLD}PR is open. Nothing merged or published.${RST}
      $PR_URL

  CI is running against it now. Once it is green:
      ./scripts/release.sh --release
EOF
  exit 0
fi

# ------------------------------------------------------ 7. wait for CI, then merge ----
step "Waiting for CI"
note "the local gates above were a fast filter; this is the run that decides"
note "watching $PR_URL (timeout ${CI_TIMEOUT}s)"
if ! timeout "$CI_TIMEOUT" gh pr checks "$RELEASE_BRANCH" --watch --fail-fast; then
  die "CI is not green — the PR stays open and nothing was merged or published.
       Fix it, commit to '$RELEASE_BRANCH', then re-run with --release."
fi
ok "CI passed"

step "Merge and tag"
confirm "Squash-merge $PR_URL into $MAIN_BRANCH, tag v$VERSION and publish?"
gh pr merge "$RELEASE_BRANCH" --squash --delete-branch \
  --subject "Release $VERSION" --body "$(printf '%s' "$NOTES" | head -60)"
ok "squash-merged into $MAIN_BRANCH"

git checkout -q "$MAIN_BRANCH"
git pull -q --ff-only origin "$MAIN_BRANCH"
git tag -a "v$VERSION" -m "revoice $VERSION"
git push -q origin "v$VERSION"
ok "tagged v$VERSION on $(git rev-parse --short HEAD)"

# -------------------------------------------------------------- 8. publish: GitHub ----
step "GitHub Release"
printf '%s\n' "$NOTES" > "$VERIFY_ENV/notes.md"
gh release create "v$VERSION" --title "revoice $VERSION" --notes-file "$VERIFY_ENV/notes.md" \
  dist/revoice-"$VERSION"-*.whl dist/revoice-"$VERSION".tar.gz >/dev/null
REL_URL=$(gh release view "v$VERSION" --json url -q .url)
ok "published $REL_URL"
note "the attached wheel and sdist are the ones built and test-installed above"

# ---------------------------------------------------------------- 9. publish: PyPI ----
if [ "$DO_PYPI" -eq 1 ]; then
  step "PyPI"
  [ -n "${UV_PUBLISH_TOKEN:-}" ] \
    || die "UV_PUBLISH_TOKEN is not set — https://pypi.org/manage/account/token/"
  confirm "Upload revoice $VERSION to PyPI? A version cannot be re-uploaded or replaced."
  uv publish dist/revoice-"$VERSION"* >/dev/null || die "upload failed"
  ok "published https://pypi.org/project/revoice/$VERSION/"
else
  note "PyPI: skipped (pass --pypi with UV_PUBLISH_TOKEN set)"
fi

# --------------------------------------------------------------- 10. publish: Pages ----
step "Pages"
note "GitHub Pages rebuilds from pages/ on the merge commit — no action needed"
note "the site reports $VERSION from the version.js committed with this release"

printf "\n%sreleased revoice %s%s  %s\n" "$GRN$BOLD" "$VERSION" "$RST" "$REL_URL"
