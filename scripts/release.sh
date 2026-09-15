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
# When it refuses, it says what to type. Repo-state problems — an existing tag, a dirty
# tree, an undated changelog, stale generated files — are collected and reported
# TOGETHER, each with the command that fixes it, because finding three problems in three
# runs is three times the work of finding them in one. Test and build failures are
# reported one at a time, since those are not fixed by typing a command, but each names
# the un-quieted command that reproduces it.
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

# Problems are COLLECTED, not fatal on sight. A release that is three commits and a date
# away from ready should say so once, with the three commands, rather than making you
# discover them one failed run at a time.
#
#   need "<what is wrong>" "<the command that fixes it>" ["<second line>" ...]
#
# Every entry must carry something runnable. "the changelog is not dated" tells you what
# to think about; the sed line tells you what to type, and that is the difference
# between a diagnostic and an instruction.
NEED_WHAT=(); NEED_FIX=()
need() {
  NEED_WHAT+=("$1"); shift
  local fix=""
  for line in "$@"; do fix+="${fix:+$'\n'}$line"; done
  NEED_FIX+=("$fix")
}
report_needs() {
  [ "${#NEED_WHAT[@]-0}" -eq 0 ] && return 0
  local n="${#NEED_WHAT[@]}" noun="things"
  [ "$n" -eq 1 ] && noun="thing"
  printf "\n%snot ready to release — %d %s to do first:%s\n" \
    "$RED$BOLD" "$n" "$noun" "$RST" >&2
  local i
  for i in "${!NEED_WHAT[@]}"; do
    printf "\n%s%d. %s%s\n" "$BOLD" "$((i + 1))" "${NEED_WHAT[$i]}" "$RST" >&2
    printf "%s\n" "${NEED_FIX[$i]}" | sed 's/^/       /' >&2
  done
  # In order: item 1 can change the version that item 2 would commit, so a numbered
  # list that is also a sequence should say it is one.
  if [ "$n" -gt 1 ]; then
    printf "\n%sdo them in order — a later step can depend on an earlier one.%s\n" \
      "$DIM" "$RST" >&2
  else
    printf "\n" >&2
  fi
  printf "%sthen re-run:%s %s\n" "$DIM" "$RST" \
    "$(printf '%s' "$0 ${ORIGINAL_ARGS[*]-}" | sed 's/ *$//')" >&2
  exit 1
}

# ---------------------------------------------------------------------- options ----
# Kept so the "then re-run" line can echo back exactly what was invoked.
# Expanded as ${ORIGINAL_ARGS[*]-} everywhere: under `set -u`, bash 3.2 —
# which is still what macOS ships — treats an empty array as unbound.
ORIGINAL_ARGS=("${@-}")
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

# BSD sed needs an empty argument after -i, GNU sed refuses one. The script suggests a
# sed command when the changelog is undated, and suggesting the wrong one is worse than
# suggesting none — so it works out which is installed rather than telling you to.
if sed --version >/dev/null 2>&1; then SED_INPLACE="sed -i"; else SED_INPLACE="sed -i ''"; fi

PY=$(command -v python3 || true)
[ -n "$PY" ] || die "python3 not found.
       Install it from https://www.python.org/downloads/  or:  brew install python"
command -v uv >/dev/null || die "uv not found — needed to build and to make a clean test env.
       Install it:  curl -LsSf https://astral.sh/uv/install.sh | sh
       or:          brew install uv"
if command -v node >/dev/null; then
  ok "node present — the JS/Python parity tests will run"
else
  warn "node not found: the JS/Python parity tests will SKIP, which is how the site and"
  note "  the tool drift apart. Install it:  brew install node"
fi
if [ "$DO_PR" -eq 1 ]; then
  command -v gh >/dev/null || die "gh (GitHub CLI) not found — needed for --pr and --release.
       Install it:  brew install gh
       Then:        gh auth login
       Or verify and build locally without publishing:  $0"
  gh auth status >/dev/null 2>&1 || die "gh is installed but not authenticated.
       Run:  gh auth login"
fi

# ------------------------------------------------------ 1. what are we releasing? ----
step "Preflight"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git rev-parse --verify "$MAIN_BRANCH" >/dev/null 2>&1 || die "no '$MAIN_BRANCH' branch here.
       Branches present: $(git branch --format='%(refname:short)' | tr '\n' ' ')
       Choose one with:  $0 --main-branch <name>"

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
  || die "the committed version is $VERSION, but --expect said $EXPECT.
       Either drop --expect, or set the version you meant:
         \$EDITOR revoice/__init__.py     # __version__ = \"$EXPECT\"
         git commit -am \"Release $EXPECT\""

# Tag first: it is the cheapest check and its message is the more useful one. A tag that
# already exists means the release is not ready at all, which is worth knowing before
# being told to tidy the working tree.
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
  NEXT=$(echo "$VERSION" | awk -F. -v OFS=. '{ $NF = $NF + 1; print }')
  TODAY=$(date -u +%Y-%m-%d)
  need "v$VERSION is already tagged — this version has shipped" \
       "Bump to the next version and write its notes:" \
       "  \$EDITOR revoice/__init__.py      # __version__ = \"$NEXT\"" \
       "  \$EDITOR CHANGELOG.md             # add a '## $NEXT - $TODAY' section" \
       "  python scripts/export_demo_baselines.py" \
       "  git commit -am \"Release $NEXT\""
else
  ok "tag v$VERSION is free"
fi

# Release ships what is committed. An uncommitted change is a change CI never saw.
if [ -n "$(git status --porcelain)" ]; then
  need "the working tree has uncommitted changes (CI can only test what is committed)" \
       "$(git status --short | sed 's/^/  /')" \
       "" \
       "Commit them:" \
       "  git add -A && git commit -m \"Release $VERSION\"" \
       "or set them aside:" \
       "  git stash -u"
else
  ok "working tree clean"
fi

# ---------------------------------------------------------- 2. consistency checks ----
step "Consistency"

# The CHANGELOG check reports WHICH of the three ways it can be wrong, and hands back the
# exact line to change. "write the notes before releasing" is a diagnosis; a sed command
# with today's date already in it is an instruction.
CHANGELOG_PROBLEM=$("$PY" - "$VERSION" <<'CHECK_EOF'
import pathlib, re, sys
v = sys.argv[1]
text = pathlib.Path("CHANGELOG.md").read_text()
m = re.search(rf'^## {re.escape(v)}\b(.*)$', text, re.M)
if not m:
    print("missing")
    raise SystemExit(0)
if "(unreleased)" in m.group(1):
    print("undated")
    raise SystemExit(0)
body = text[m.end():]
nxt = re.search(r'^## ', body, re.M)
entry = (body[:nxt.start()] if nxt else body).strip()
print("empty" if len(entry) < 40 else "ok")
CHECK_EOF
)
TODAY=$(date -u +%Y-%m-%d)
case "$CHANGELOG_PROBLEM" in
  ok) ok "CHANGELOG has dated notes for $VERSION" ;;
  undated)
    need "CHANGELOG.md still marks $VERSION as (unreleased)" \
         "Date the heading:" \
         "  $SED_INPLACE 's/^## $VERSION (unreleased)\$/## $VERSION - $TODAY/' CHANGELOG.md" \
         "  git commit -am \"Release $VERSION\"" ;;
  missing)
    need "CHANGELOG.md has no '## $VERSION' section" \
         "Add one at the top of the file, under '# Changelog':" \
         "" \
         "  ## $VERSION - $TODAY" \
         "" \
         "  ### Added" \
         "  - what changed, and why someone should care" \
         "" \
         "  git commit -am \"Release $VERSION\"" ;;
  empty)
    need "the '## $VERSION' section in CHANGELOG.md has no notes in it" \
         "A release with no notes helps nobody. Write what changed:" \
         "  \$EDITOR CHANGELOG.md" \
         "  git commit -am \"Release $VERSION\"" ;;
esac

DERIVED=$(uv run --quiet python -c 'import revoice; print(revoice.__version__)' 2>/dev/null || echo "?")
if [ "$DERIVED" = "$VERSION" ]; then
  ok "runtime and packaging agree on $VERSION"
else
  need "the installed package reports $DERIVED but the source says $VERSION" \
       "The environment is stale. Re-sync it:" \
       "  uv sync --all-extras"
fi

if uv run --quiet python scripts/export_demo_baselines.py --check >/dev/null 2>&1; then
  ok "pages/version.js, population.json, voices.json and engine-constants.js are current"
else
  need "the site's generated files are stale (the pages would ship the wrong version or weights)" \
       "Regenerate and commit them:" \
       "  python scripts/export_demo_baselines.py" \
       "  git add pages/ && git commit -m \"Regenerate site data for $VERSION\""
fi

# Everything above is a repo-state problem with a known fix, so they are reported
# together. Nothing below this line can be answered by a command you type once.
report_needs

# ------------------------------------------------------ 3. environment (CI parity) ----
step "Environment"
# The gates below claim to be "the same gates CI runs", and that claim is only true if
# the environment is the same too. .github/workflows/ci.yml does exactly this pair
# before testing; without it, tests/test_core_extra.py exercises .docx/.pptx/.pdf
# extraction whose libraries are absent and three tests fail for a reason that has
# nothing to do with the release.
#
# This is not a violation of the read-only contract. That contract is about what gets
# COMMITTED and shipped — no version bumps, no changelog edits, no regenerated site
# data. .venv/ is gitignored and is not part of what ships; refusing to prepare it
# would mean the local gates quietly test something other than what CI tests, which is
# the failure the contract exists to prevent.
uv sync --quiet --all-extras 2>/dev/null || die "could not sync the environment.
       See why:  uv sync --all-extras"
uv pip install --quiet pytest pytest-cov ruff 2>/dev/null || die "could not install the test tools.
       See why:  uv pip install pytest pytest-cov ruff"
ok "environment matches CI (uv sync --all-extras, plus pytest/pytest-cov/ruff)"

# ------------------------------------------------------------------- 4. test (CI) ----
step "Test (the same gates CI runs)"

# These fail one at a time on purpose — unlike the repo-state checks above, a broken test
# is not something you fix by typing a command, and running the rest of the suite after
# the first failure just buries the output you need. What each DOES give you is the exact
# command to reproduce it, without --quiet, so the next thing you run shows you the error.
gate() {
  local label="$1" fix="$2"; shift 2
  if "$@" >/dev/null 2>&1; then
    ok "$label"
  else
    printf "\n%sfailed:%s %s\n\n" "$RED$BOLD" "$RST" "$label" >&2
    printf "    Reproduce it:\n       %s\n\n" "$fix" >&2
    printf "    Then commit the fix and re-run:  %s\n" \
      "$(printf '%s' "$0 ${ORIGINAL_ARGS[*]-}" | sed 's/ *$//')" >&2
    exit 1
  fi
}

gate "privacy gate" \
     "uv run python scripts/check_no_user_data.py" \
     uv run --quiet python scripts/check_no_user_data.py
gate "ruff, zero warnings" \
     "uv run ruff check revoice/ tests/ scripts/    (add --fix for the automatic ones)" \
     uv run --quiet ruff check revoice/ tests/ scripts/
gate "tests pass at 100% coverage" \
     "uv run pytest tests/ -q --cov=revoice --cov-report=term-missing" \
     uv run --quiet pytest tests/ -q --cov=revoice --cov-fail-under=100
gate "voice-metric bench runs clean" \
     "uv run revoice bench examples/voices --lengths 50,200 -n 10 --no-content-control" \
     uv run --quiet revoice bench examples/voices --lengths 50,200 -n 10 --no-content-control

# -------------------------------------------------------------------- 5. build all ----
step "Build"
rm -rf dist
uv build >/dev/null 2>&1 || die "the build failed.
       See why:  uv build
       Then commit the fix and re-run:  $0 ${ORIGINAL_ARGS[*]-}"
[ -f dist/revoice-"$VERSION".tar.gz ] || die "no sdist for $VERSION was produced.
       Built instead: $(ls dist 2>/dev/null | tr '\n' ' ')
       That usually means pyproject.toml and revoice/__init__.py disagree. Check:
         uv run python -c 'import revoice; print(revoice.__version__)'"
ls dist/revoice-"$VERSION"-*.whl >/dev/null 2>&1 || die "no wheel for $VERSION was produced.
       Built instead: $(ls dist 2>/dev/null | tr '\n' ' ')
       See why:  uv build"
ls dist | sed 's/^/      /'

# Install the wheel somewhere clean: the only check that catches a package which builds
# fine and is broken on arrival — a missing package-data entry, a bad manifest.
VERIFY_ENV=$(mktemp -d)
trap 'rm -rf "$VERIFY_ENV"' EXIT
uv venv --quiet "$VERIFY_ENV/venv" >/dev/null 2>&1
uv pip install --quiet --python "$VERIFY_ENV/venv/bin/python" dist/revoice-"$VERSION"-*.whl
INSTALLED=$("$VERIFY_ENV/venv/bin/revoice" --version | awk '{print $NF}')
[ "$INSTALLED" = "$VERSION" ] || die "the built wheel reports version '$INSTALLED' but the source says '$VERSION'.
       The packaging metadata is out of step with revoice/__init__.py. Check:
         grep -n 'version' pyproject.toml
         uv run python -c 'import revoice; print(revoice.__version__)'"
"$VERIFY_ENV/venv/bin/python" - <<'PYEOF' || die "the built wheel is missing package data — it would install and then fail on use.
       Check the package-data globs:
         grep -n -A5 'package-data\\|force-include\\|artifacts' pyproject.toml
       Rebuild and inspect what actually went in:
         uv build && python -m zipfile -l dist/revoice-$VERSION-*.whl"
import importlib.resources as r
for name in ("rubric/README.md", "voicemetric/README.md", "static/index.html"):
    pkg, _, rest = name.partition("/")
    assert (r.files("revoice") / pkg / rest).is_file(), f"missing from wheel: {name}"
PYEOF
ok "wheel installs cleanly, reports $VERSION, carries its package data"

# ---------------------------------------------------------------------- 6. summary ----
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

# ------------------------------------------------------------------ 7. push and PR ----
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

# ------------------------------------------------------ 8. wait for CI, then merge ----
step "Waiting for CI"
note "the local gates above were a fast filter; this is the run that decides"
note "watching $PR_URL (timeout ${CI_TIMEOUT}s)"
if ! timeout "$CI_TIMEOUT" gh pr checks "$RELEASE_BRANCH" --watch --fail-fast; then
  die "CI is not green — the PR stays open and nothing was merged or published.
       Look at what failed:
         gh pr checks $RELEASE_BRANCH
         gh run view --log-failed
       Fix it, then:
         git commit -am \"...\" && git push
         $0 --release"
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

# -------------------------------------------------------------- 9. publish: GitHub ----
step "GitHub Release"
printf '%s\n' "$NOTES" > "$VERIFY_ENV/notes.md"
gh release create "v$VERSION" --title "revoice $VERSION" --notes-file "$VERIFY_ENV/notes.md" \
  dist/revoice-"$VERSION"-*.whl dist/revoice-"$VERSION".tar.gz >/dev/null
REL_URL=$(gh release view "v$VERSION" --json url -q .url)
ok "published $REL_URL"
note "the attached wheel and sdist are the ones built and test-installed above"

# --------------------------------------------------------------- 10. publish: PyPI ----
if [ "$DO_PYPI" -eq 1 ]; then
  step "PyPI"
  [ -n "${UV_PUBLISH_TOKEN:-}" ] \
    || die "--pypi was given but UV_PUBLISH_TOKEN is not set.
       Create a token at https://pypi.org/manage/account/token/ then:
         export UV_PUBLISH_TOKEN=pypi-...
       Or drop --pypi to publish to GitHub only (the default)."
  confirm "Upload revoice $VERSION to PyPI? A version cannot be re-uploaded or replaced."
  uv publish dist/revoice-"$VERSION"* >/dev/null || die "the PyPI upload failed.
       The GitHub release was already published, so do not re-run the whole script.
       Retry just the upload:
         uv publish dist/revoice-$VERSION*
       Note: the name 'revoice' is already taken on PyPI by an unrelated package."
  ok "published https://pypi.org/project/revoice/$VERSION/"
else
  note "PyPI: skipped (pass --pypi with UV_PUBLISH_TOKEN set)"
fi

# --------------------------------------------------------------- 11. publish: Pages ----
step "Pages"
note "GitHub Pages rebuilds from pages/ on the merge commit — no action needed"
note "the site reports $VERSION from the version.js committed with this release"

printf "\n%sreleased revoice %s%s  %s\n" "$GRN$BOLD" "$VERSION" "$RST" "$REL_URL"
