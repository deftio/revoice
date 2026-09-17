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
#   ./scripts/release.sh             verify, test, build — report readiness, touch nothing
#   ./scripts/release.sh --fix       ...and do the mechanical repairs it finds
#   ./scripts/release.sh --pr        push the branch and open a PR into main
#   ./scripts/release.sh --release   wait for CI green, squash-merge, tag, publish
#
# Without --fix nothing in the repository is touched. With it, the script performs the
# repairs that are work rather than decisions — dating the changelog heading, regenerating
# derived site data — and commits exactly those files, echoing every command it runs.
# It never chooses a version number, writes release notes, or commits anything you were
# editing: those are yours, and it still stops for them.
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

# Echo the command, then run it. Anything this script does to git is visible as the
# git command you would have typed, so "it did something to my repo" is never a mystery.
run_cmd() { printf "    %s$ %s%s\n" "$DIM" "$*" "$RST"; "$@"; }

# Problems are COLLECTED, not fatal on sight. A release that is three commits and a date
# away from ready should say so once, with the three commands, rather than making you
# discover them one failed run at a time.
#
#   need "<what is wrong>" "<the command that fixes it>" ["<second line>" ...]
#
# Every entry must carry something runnable. "the changelog is not dated" tells you what
# to think about; the sed line tells you what to type, and that is the difference
# between a diagnostic and an instruction.
# NEED_COUNT is kept by hand rather than read from the array length. `${#arr[@]}` on an
# empty array is an unbound-variable error under `set -u` on bash 3.2 (macOS), and the
# obvious guard against that, `${#arr[@]-0}`, is a "bad substitution" on bash 5 (Linux,
# and therefore CI) because ${#...} does not take a default. A plain integer is correct
# on both, and this cost a CI round trip to learn.
NEED_WHAT=(); NEED_FIX=(); NEED_COUNT=0
REPAIRED=""   # files --fix touched, so only those get committed
need() {
  NEED_WHAT+=("$1"); shift
  NEED_COUNT=$((NEED_COUNT + 1))
  local fix=""
  for line in "$@"; do fix+="${fix:+$'\n'}$line"; done
  NEED_FIX+=("$fix")
}
report_needs() {
  [ "$NEED_COUNT" -eq 0 ] && return 0
  local n="$NEED_COUNT" noun="things"
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
DO_PR=0; DO_RELEASE=0; DO_PYPI=0; ASSUME_YES=0; DO_FIX=0
MAIN_BRANCH="main"; CI_TIMEOUT=1800; EXPECT=""
usage() {
  sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'USAGE'
Options:
  --fix                do the mechanical repairs (date the changelog, regenerate the
                       site data) and commit them, instead of printing what to type
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
    --fix) DO_FIX=1 ;;
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
# Two forms, and they are not interchangeable. SED_INPLACE is the string SHOWN to you;
# SED_ARGS is what actually gets run. Storing the BSD form as the string "sed -i ''" and
# expanding it unquoted does not pass an empty argument — the quotes survive expansion as
# a literal two-character backup suffix, so sed edits the file AND leaves a "CHANGELOG.md''"
# beside it. The release caught that itself, on its own dirty-tree gate, one step later.
if sed --version >/dev/null 2>&1; then
  SED_INPLACE="sed -i"; SED_ARGS=(-i)
else
  SED_INPLACE="sed -i ''"; SED_ARGS=(-i "")
fi

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

# The main branch is needed to PUBLISH — it is the PR base and the merge target. It is
# not needed to verify, and demanding it here made the script unusable in the one
# environment whose opinion decides the release: `actions/checkout` on a pull_request
# fetches only refs/pull/N/merge at depth 1, so the checkout is a detached HEAD with no
# local branches AND no remote-tracking refs. Not even origin/main exists.
#
# This took two attempts. The first fix accepted origin/main as a fallback and was
# verified against a `git worktree`, which shares the parent repository's refs — so
# origin/main was there and the reproduction passed while CI kept failing. The test
# below now builds a standalone repository with no remotes and no branches, which is
# what CI actually hands you.
if [ "$DO_PR" -eq 1 ]; then
  if [ "$BRANCH" = "HEAD" ]; then
    die "HEAD is detached, so there is no branch to release from.
       Check out the branch you mean to ship:
         git checkout $MAIN_BRANCH
       Or verify and build without publishing:
         $0"
  fi
  # A missing local branch that exists on origin is not a decision anybody needs to make
  # — it is one fetch. Telling someone to go and type it, then re-run a script that has
  # already done several minutes of work, is not a gate, it is an obstacle. Gates are for
  # things only you can settle: what version this is, what the notes say, whether the
  # tests pass. Fetching a ref is not one of those, so the script does it and shows the
  # command it used.
  if ! git rev-parse --verify "$MAIN_BRANCH" >/dev/null 2>&1; then
    if git rev-parse --verify "origin/$MAIN_BRANCH" >/dev/null 2>&1; then
      note "no local '$MAIN_BRANCH'; creating it from origin/$MAIN_BRANCH"
      run_cmd git branch "$MAIN_BRANCH" "origin/$MAIN_BRANCH"
    elif git ls-remote --exit-code --heads origin "$MAIN_BRANCH" >/dev/null 2>&1; then
      note "no local '$MAIN_BRANCH'; fetching it from origin"
      run_cmd git fetch -q origin "$MAIN_BRANCH:$MAIN_BRANCH"
    else
      die "no '$MAIN_BRANCH' branch here or on origin, and --pr needs it as the PR base.
       Branches here:   $(git branch --format='%(refname:short)' | tr '\n' ' ')
       Branches remote: $(git ls-remote --heads origin 2>/dev/null | sed 's#.*refs/heads/##' | tr '\n' ' ')
       Name another:    $0 --main-branch <name> ${ORIGINAL_ARGS[*]-}"
    fi
    ok "$MAIN_BRANCH available as the PR base"
  fi
fi

# The version comes from the CODE, by asking it. This script used to carry its own
# regex over revoice/__init__.py — a second implementation of something the package
# already exposes as revoice.version(), and therefore a second source of truth that
# could drift. It could not even tell that it had: the "runtime and packaging agree"
# check below existed purely to compare the script's parse against the package's, which
# is a check that only needs to exist when you have made the mistake of parsing.
#
# Everything else already derives from the same place: pyproject.toml reads
# `attr: revoice.__version__`, and pages/version.js is generated by
# scripts/export_demo_baselines.py. Now the release does too.
VERSION=$(uv run --quiet python -c 'import revoice; print(revoice.version())' 2>/dev/null) \
  || die "could not read the version from the package.
       The release version comes from the code, not from this script, so the package
       has to be importable. Sync the environment and try again:
         uv sync --all-extras
       If that succeeds and this still fails, revoice/__init__.py is the place to look."
[ -n "$VERSION" ] || die "revoice.version() returned nothing.
       Check revoice/__init__.py defines __version__ and version()."
note "version   $VERSION   (from revoice.version())"
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
  # Deliberately no suggested number. What the next version IS — patch, minor, major —
  # is a judgement about what changed, and the script has no standing to make it. It
  # names the file where that decision is recorded and gets out of the way.
  need "v$VERSION is already tagged — this version has shipped" \
       "Set the next version in the code, then write its notes:" \
       "  \$EDITOR revoice/__init__.py      # __version__ — the single source of truth" \
       "  \$EDITOR CHANGELOG.md             # a '## <version> - $(date -u +%Y-%m-%d)' section" \
       "  python scripts/export_demo_baselines.py   # propagates it to the site" \
       "  git commit -am \"Release <version>\""
else
  ok "tag v$VERSION is free"
fi

# ---------------------------------------------------------- 2. consistency checks ----
step "Consistency"

# The CHANGELOG check reports WHICH of the three ways it can be wrong, and hands back the
# exact line to change. "write the notes before releasing" is a diagnosis; a sed command
# with today's date already in it is an instruction.
# `VAR=$(cmd)` under `set -e` exits the script when cmd fails, so the branches below
# that exist precisely to HANDLE a failure could never run. Both captures suspend
# errexit deliberately and inspect the status themselves.
set +e
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
CHANGELOG_RC=$?
set -e
[ "$CHANGELOG_RC" -eq 0 ] || die "could not read CHANGELOG.md.
       Check that it exists and is readable:  ls -l CHANGELOG.md"
TODAY=$(date -u +%Y-%m-%d)
case "$CHANGELOG_PROBLEM" in
  ok) ok "CHANGELOG has dated notes for $VERSION" ;;
  undated)
    # Dating a heading is work, not a decision: the date is today and there is nothing
    # to choose. Writing the notes IS a decision, which is why the 'empty' case below
    # still stops.
    if [ "$DO_FIX" -eq 1 ]; then
      confirm "Date the CHANGELOG heading '## $VERSION' as $TODAY?"
      run_cmd sed "${SED_ARGS[@]}" "s/^## $VERSION (unreleased)\$/## $VERSION - $TODAY/" CHANGELOG.md
      REPAIRED="$REPAIRED CHANGELOG.md"
      ok "CHANGELOG dated $TODAY"
    else
      need "CHANGELOG.md still marks $VERSION as (unreleased)" \
           "Date the heading:" \
           "  $SED_INPLACE 's/^## $VERSION (unreleased)\$/## $VERSION - $TODAY/' CHANGELOG.md" \
           "  git commit -am \"Release $VERSION\"" \
           "" \
           "or let this script do it:  $0 --fix ${ORIGINAL_ARGS[*]-}"
    fi ;;
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

# The old "runtime and packaging agree" check lived here. It compared this script's own
# parse of revoice/__init__.py against the package's, and with the parse gone there is
# nothing left to compare — both sides were always the same number. The claim it was
# reaching for, that what gets BUILT carries this version, is asserted where it can
# actually be tested: the wheel is installed into a clean environment in the build stage
# and asked its version there.

# Exit 2 means "cannot verify here", not "stale" — the population was built from a
# corpus this checkout does not have, and regenerating would replace it with a smaller
# one. Telling someone to regenerate in that state is an instruction to break the file.
set +e
GEN_OUT=$(uv run --quiet python scripts/export_demo_baselines.py --check 2>&1)
GEN_RC=$?
set -e
case "$GEN_RC" in
  0) ok "pages/version.js, population.json, voices.json and engine-constants.js are current" ;;
  2) need "the generated site files cannot be verified in this checkout" \
          "$(printf '%s' "$GEN_OUT" | sed 's/^/  /')" ;;
  *) if [ "$DO_FIX" -eq 1 ]; then
       confirm "Regenerate the site's generated files from the Python?"
       run_cmd uv run --quiet python scripts/export_demo_baselines.py
       REPAIRED="$REPAIRED pages"
       ok "site data regenerated"
     else
       need "the site's generated files are stale (the pages would ship the wrong version or weights)" \
            "Regenerate and commit them:" \
            "  python scripts/export_demo_baselines.py" \
            "  git add pages/ && git commit -m \"Regenerate site data for $VERSION\"" \
            "" \
            "or let this script do it:  $0 --fix ${ORIGINAL_ARGS[*]-}"
     fi ;;
esac

# Everything above is a repo-state problem with a known fix, so they are reported
# together. Nothing below this line can be answered by a command you type once.
# Now, and not before: the repairs above legitimately dirty the tree, so checking first
# would have reported a problem the script was about to create.
if [ -n "$(git status --porcelain)" ]; then
  if [ "$DO_FIX" -eq 1 ] && [ -n "$REPAIRED" ]; then
    # Commit ONLY what the repairs touched. Whatever else you had open is yours, and a
    # release script sweeping it into a commit is exactly the surprise nobody wants.
    step "Commit the repairs"
    confirm "Commit$REPAIRED as \"Release $VERSION\"?"
    # shellcheck disable=SC2086
    run_cmd git add $REPAIRED
    run_cmd git commit -q -m "Release $VERSION"
    ok "committed $(git rev-parse --short HEAD)"
  fi
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
else
  ok "working tree clean"
fi

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

# ---------------------------------------------- 7. already shipped? finish the job ----
# A release can arrive here half-done: the PR was merged on GitHub — by you, by
# auto-merge, by someone else — and then nobody tagged it or published the artefacts.
# The script used to have no idea. It would cut a fresh branch off a main that already
# carried the content and open a second PR with an empty diff, and the only way to
# actually finish was to type the tag and release commands by hand.
#
# So it asks the obvious question first: is this version already on the main branch?
# If HEAD is main, main matches its remote, and the tag is still missing, then the merge
# half is done and only the publish half is left.
ALREADY_ON_MAIN=0
if [ "$BRANCH" = "$MAIN_BRANCH" ] \
   && git rev-parse -q --verify "origin/$MAIN_BRANCH" >/dev/null \
   && [ -z "$(git diff "origin/$MAIN_BRANCH" -- . 2>/dev/null)" ] \
   && [ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$MAIN_BRANCH")" ]; then
  ALREADY_ON_MAIN=1
fi

if [ "$ALREADY_ON_MAIN" -eq 1 ]; then
  step "Already merged"
  note "$VERSION is already on $MAIN_BRANCH at $(git rev-parse --short HEAD)"
  note "nothing to branch, push or merge — only the tag and the release are missing"

  if [ "$DO_RELEASE" -eq 0 ]; then
    cat <<EOF

  ${BOLD}$VERSION is already merged into $MAIN_BRANCH.${RST}
  There is no PR to open. What is left is the tag and the GitHub Release:

      $0 --release
EOF
    exit 0
  fi

  step "Waiting for CI on $MAIN_BRANCH"
  note "the local gates above were a fast filter; this is the run that decides"
  MAIN_RUN=$(gh run list --branch "$MAIN_BRANCH" --limit 1 --json databaseId,conclusion,status \
               -q '.[0] | "\(.databaseId) \(.status) \(.conclusion)"' 2>/dev/null || true)
  case "$MAIN_RUN" in
    *"completed success"*) ok "CI green on $MAIN_BRANCH (run ${MAIN_RUN%% *})" ;;
    "") warn "no CI run found for $MAIN_BRANCH — publishing on the local gates alone" ;;
    *) die "the latest CI run on $MAIN_BRANCH is '${MAIN_RUN#* }', not a green one.
       Look at it:  gh run view ${MAIN_RUN%% *} --log-failed
       A release is only as good as the run that validated the commit it points at." ;;
  esac
else

# ------------------------------------------------------------------ 7b. push and PR ----
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

# GitHub registers the workflow run a moment AFTER the PR is created, and until it does
# `gh pr checks` prints "no checks reported" and exits non-zero. Watching immediately
# therefore reads a race as a failure — which it did: 0.1.11's first attempt stopped with
# "CI is not green" while the run was still in_progress and went on to pass. Wait for a
# run to exist before asking how it is doing.
note "waiting for GitHub to register the workflow run"
CHECKS_READY=0
for _ in $(seq 1 24); do        # up to two minutes
  if [ -n "$(gh run list --branch "$RELEASE_BRANCH" --limit 1 \
               --json databaseId -q '.[0].databaseId' 2>/dev/null)" ]; then
    CHECKS_READY=1
    break
  fi
  sleep 5
done
[ "$CHECKS_READY" -eq 1 ] || die "no CI run appeared for '$RELEASE_BRANCH' after two minutes.
       The PR is open and nothing was merged. Check that the workflow is enabled:
         gh workflow list
         $PR_URL
       Then:  $0 --release"
ok "CI run registered"

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

step "Merge"
confirm "Squash-merge $PR_URL into $MAIN_BRANCH, tag v$VERSION and publish?"
run_cmd gh pr merge "$RELEASE_BRANCH" --squash --delete-branch \
  --subject "Release $VERSION" --body "$(printf '%s' "$NOTES" | head -60)"
ok "squash-merged into $MAIN_BRANCH"

run_cmd git checkout -q "$MAIN_BRANCH"
# NOT --ff-only. The squash merge that just happened REPLACED this branch's commits with
# one new commit upstream, so local main and origin/main have diverged by construction —
# every commit we pushed is now an ancestor of nothing, and their content lives in the
# squash. Asking for a fast-forward here fails every single time, which is what left
# 0.1.10 and then 0.1.11 merged-but-untagged.
#
# Resetting is safe precisely because of what a squash merge is: the tree we pushed and
# the tree upstream are identical, so nothing local is lost. That is checked rather than
# assumed, and the reset is refused if it is not true.
run_cmd git fetch -q origin "$MAIN_BRANCH"
if [ -n "$(git diff "origin/$MAIN_BRANCH" "$RELEASE_BRANCH" 2>/dev/null)" ]; then
  die "the squash merge on origin/$MAIN_BRANCH does not match what was reviewed.
       Nothing was tagged or published. Compare them before going further:
         git diff origin/$MAIN_BRANCH $RELEASE_BRANCH"
fi
run_cmd git reset --hard -q "origin/$MAIN_BRANCH"
ok "$MAIN_BRANCH now at $(git rev-parse --short HEAD) (the squash commit)"

fi   # end of the "not already on main" branch

# Tagging is the same work whichever way we got here: main carries the version, CI is
# green on it, and the tag is what turns that commit into the release.
step "Tag"
confirm "Tag v$VERSION on $(git rev-parse --short HEAD) and publish the GitHub Release?"
run_cmd git tag -a "v$VERSION" -m "revoice $VERSION"
run_cmd git push -q origin "v$VERSION"
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
