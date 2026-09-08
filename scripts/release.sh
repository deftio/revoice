#!/usr/bin/env bash
#
# revoice release: bump, verify, build, then ship through GitHub the way a human would —
# a pull request that CI must pass before anything is merged or published.
#
# Four steps, each opting into more. Nothing before --pr touches the remote.
#
#   ./scripts/release.sh --patch            check + build, report what WOULD happen
#   ./scripts/release.sh --patch --commit   bump and commit on a release branch, locally
#   ./scripts/release.sh --patch --pr       push the branch and open a PR into main
#   ./scripts/release.sh --patch --release  wait for CI green, squash-merge the PR, tag,
#                                           and publish a GitHub Release with the wheel
#
# The local checks are a fast filter, not the authority. `--release` blocks on the CI run
# GitHub actually performs against the merge commit, and refuses to merge or publish if
# it is red — a release whose only evidence is "it passed on my laptop" is the thing this
# script exists to prevent.
#
# What it verifies, cheapest failure first:
#   1. clean-ish tree, known branch, tools present, gh authenticated (for --pr onward)
#   2. the CHANGELOG has an "(unreleased)" section with real notes for exactly this version
#   3. generated artefacts (pages/version.js, population.json, voices.json) regenerate —
#      the site embeds the version and the metric signature, so a stale one ships a lie
#   4. privacy gate · ruff · pytest at 100% coverage · bench smoke
#   5. sdist + wheel build, and the wheel installs into a throwaway venv and reports the
#      right version — the only check that catches a package broken on arrival
#   6. (--release) the remote CI run on the PR is green
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
BUMP=""; EXPLICIT=""; DO_COMMIT=0; DO_PR=0; DO_RELEASE=0; ASSUME_YES=0
MAIN_BRANCH="main"; CI_TIMEOUT=1800
usage() {
  sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'USAGE'
Options:
  --patch | --minor | --major   bump the version by that component
  --version X.Y.Z               set an explicit version
  --commit                      bump and commit on a release branch, locally
  --pr                          push the branch and open a PR into main (implies --commit)
  --release                     wait for CI, squash-merge the PR, tag, publish a
                                GitHub Release with the built artefacts (implies --pr)
  --yes                         do not prompt (for CI; think before using it locally)
  --main-branch NAME            target branch, default "main"
  --ci-timeout SECONDS          how long to wait for CI, default 1800
  -h, --help                    this text
USAGE
}
while [ $# -gt 0 ]; do
  case "$1" in
    --patch|--minor|--major) BUMP="${1#--}" ;;
    --version) EXPLICIT="${2:-}"; shift ;;
    --commit) DO_COMMIT=1 ;;
    --pr) DO_PR=1; DO_COMMIT=1 ;;
    --release) DO_RELEASE=1; DO_PR=1; DO_COMMIT=1 ;;
    --push) die "--push is now --pr (open a PR) or --release (merge and publish)" ;;
    --ci-timeout) CI_TIMEOUT="${2:-1800}"; shift ;;
    --yes|-y) ASSUME_YES=1 ;;
    --main-branch) MAIN_BRANCH="${2:-main}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1  (try --help)" ;;
  esac
  shift
done
[ -n "$BUMP" ] || [ -n "$EXPLICIT" ] || { usage; die "say which version: --patch/--minor/--major or --version X.Y.Z"; }

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
  command -v gh >/dev/null || die "gh (GitHub CLI) not found — needed to open the PR; see https://cli.github.com"
  gh auth status >/dev/null 2>&1 || die "gh is not authenticated — run: gh auth login"
fi

# ------------------------------------------------------------------- 1. preflight ----
step "Preflight"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
note "branch: $BRANCH   release branch: $MAIN_BRANCH"
git rev-parse --verify "$MAIN_BRANCH" >/dev/null 2>&1 || die "no '$MAIN_BRANCH' branch in this repo"

DIRTY=$(git status --porcelain | grep -v '^?? ' || true)
UNTRACKED=$(git status --porcelain | grep '^?? ' || true)
if [ -n "$DIRTY" ] || [ -n "$UNTRACKED" ]; then
  note "working tree has changes; they will be part of the release commit:"
  git status --short | sed 's/^/      /'
else
  ok "working tree clean"
fi

CURRENT=$("$PY" - <<'EOF'
import re, pathlib
print(re.search(r'^version = "([^"]+)"', pathlib.Path("pyproject.toml").read_text(), re.M).group(1))
EOF
)
NEW=$("$PY" - "$CURRENT" "$BUMP" "$EXPLICIT" <<'EOF'
import sys
cur, bump, explicit = sys.argv[1], sys.argv[2], sys.argv[3]
if explicit:
    parts = explicit.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), f"not semver: {explicit}"
    print(explicit); raise SystemExit
major, minor, patch = (int(x) for x in cur.split("."))
print({"major": f"{major+1}.0.0", "minor": f"{major}.{minor+1}.0",
       "patch": f"{major}.{minor}.{patch+1}"}[bump])
EOF
)
note "version: $CURRENT  ->  ${BOLD}$NEW${RST}"
git rev-parse -q --verify "refs/tags/v$NEW" >/dev/null && die "tag v$NEW already exists"
ok "tag v$NEW is free"

# ------------------------------------------------------------------- 2. changelog ----
step "Changelog"
"$PY" - "$NEW" <<'EOF' || exit 1
import pathlib, re, sys
new = sys.argv[1]
text = pathlib.Path("CHANGELOG.md").read_text()
m = re.search(r'^## (\d+\.\d+\.\d+) \(unreleased\)', text, re.M)
if not m:
    print(f"    no '## X.Y.Z (unreleased)' section found in CHANGELOG.md"); raise SystemExit(1)
if m.group(1) != new:
    print(f"    CHANGELOG's top unreleased section is {m.group(1)}, but releasing {new}.")
    print(f"    Retitle it to '## {new} (unreleased)', or release {m.group(1)} instead.")
    raise SystemExit(1)
body = text[m.end():]
nxt = re.search(r'^## ', body, re.M)
entry = (body[:nxt.start()] if nxt else body).strip()
if len(entry) < 40:
    print("    the unreleased section is empty — a release with no notes helps nobody")
    raise SystemExit(1)
EOF
ok "CHANGELOG has notes for $NEW"

# ------------------------------------------- 3. bump + regenerate the generated bits ----
step "Version and generated artefacts"
"$PY" - "$CURRENT" "$NEW" <<'EOF'
import pathlib, sys
cur, new = sys.argv[1], sys.argv[2]
for path, old, rep in (("pyproject.toml", f'version = "{cur}"', f'version = "{new}"'),
                       ("revoice/__init__.py", f'__version__ = "{cur}"', f'__version__ = "{new}"')):
    p = pathlib.Path(path); t = p.read_text()
    assert t.count(old) == 1, f"{path}: expected exactly one {old!r}"
    p.write_text(t.replace(old, rep))
print(f"    set {new} in pyproject.toml and revoice/__init__.py")
EOF
# The site embeds the version and the metric's signature; regenerate so they cannot lag.
uv run --quiet python scripts/export_demo_baselines.py >/dev/null \
  || die "export_demo_baselines.py failed — the site's generated files would ship stale"
ok "pages/version.js, population.json and voices.json regenerated"

# ------------------------------------------------------------------ 4. verify (CI) ----
step "Verify (the same gates CI runs)"
uv run --quiet python scripts/check_no_user_data.py >/dev/null && ok "privacy gate"
uv run --quiet ruff check revoice/ tests/ scripts/ >/dev/null && ok "ruff, zero warnings"
uv run --quiet pytest tests/ -q --cov=revoice --cov-fail-under=100 >/dev/null \
  && ok "tests pass at 100% coverage"
uv run --quiet revoice bench examples/voices --lengths 50,200 -n 10 --no-content-control >/dev/null \
  && ok "voice-metric bench runs clean"

# -------------------------------------------------------------------- 5. build all ----
step "Build"
rm -rf dist
uv build >/dev/null 2>&1 || die "build failed (rerun 'uv build' to see why)"
ls dist | sed 's/^/      /'
[ -f dist/revoice-"$NEW".tar.gz ] || die "sdist for $NEW not produced"
ls dist/revoice-"$NEW"-*.whl >/dev/null 2>&1 || die "wheel for $NEW not produced"
ok "sdist + wheel built"

# Install the wheel somewhere clean. This is the only check that catches a package that
# builds fine and is broken on arrival — a missing package-data entry, a bad manifest.
VERIFY_ENV=$(mktemp -d)
trap 'rm -rf "$VERIFY_ENV"' EXIT
uv venv --quiet "$VERIFY_ENV/venv" >/dev/null 2>&1
uv pip install --quiet --python "$VERIFY_ENV/venv/bin/python" dist/revoice-"$NEW"-*.whl
INSTALLED=$("$VERIFY_ENV/venv/bin/revoice" --version | awk '{print $NF}')
[ "$INSTALLED" = "$NEW" ] || die "installed wheel reports '$INSTALLED', expected '$NEW'"
"$VERIFY_ENV/venv/bin/python" - <<'EOF' || die "the built wheel is missing package data"
import importlib.resources as r
for name in ("rubric/README.md", "voicemetric/README.md", "static/index.html"):
    pkg, _, rest = name.partition("/")
    assert (r.files("revoice") / pkg / rest).is_file(), f"missing from wheel: {name}"
print("    wheel carries both engine READMEs and the GUI")
EOF
ok "wheel installs cleanly and reports $NEW"

# ---------------------------------------------------------------------- 6. summary ----
step "Summary"
note "version     $CURRENT -> $NEW"
note "artefacts   $(ls dist | tr '\n' ' ')"
note "branch      $BRANCH"
if [ "$DO_COMMIT" -eq 0 ]; then
  cat <<EOF

  ${BOLD}Nothing was committed.${RST} The version files and generated artefacts were
  updated in your working tree so you can inspect them; ${DIM}git checkout${RST} reverts them.

  Next:
      ./scripts/release.sh --version $NEW --commit    # commit on a release branch
      ./scripts/release.sh --version $NEW --pr        # ...and open a PR
      ./scripts/release.sh --version $NEW --release   # ...and merge + publish once CI is green
EOF
  exit 0
fi

# ------------------------------------------------------------- 7. commit on a branch ----
step "Commit"
DATE=$(date -u +%Y-%m-%d)
"$PY" - "$NEW" "$DATE" <<'DATESTAMP'
import pathlib, sys
new, date = sys.argv[1], sys.argv[2]
p = pathlib.Path("CHANGELOG.md"); t = p.read_text()
p.write_text(t.replace(f"## {new} (unreleased)", f"## {new} - {date}", 1))
print(f"    CHANGELOG: {new} dated {date}")
DATESTAMP

# The release always lands on its own branch, so main only ever moves through a
# reviewed, CI-checked squash merge. Starting from main, that branch is made here.
RELEASE_BRANCH="$BRANCH"
if [ "$BRANCH" = "$MAIN_BRANCH" ]; then
  RELEASE_BRANCH="release/v$NEW"
  confirm "Create branch '$RELEASE_BRANCH' off $MAIN_BRANCH and commit release $NEW there?"
  git checkout -q -b "$RELEASE_BRANCH"
  ok "branched $RELEASE_BRANCH"
else
  confirm "Commit release $NEW on '$RELEASE_BRANCH'?"
fi

NOTES=$(sed -n "/^## $NEW /,/^## /p" CHANGELOG.md | sed '1d;$d')
git add -A
git commit -q -F - <<EOF
Release $NEW

$(printf '%s' "$NOTES" | head -60)
EOF
ok "committed $(git rev-parse --short HEAD) on $RELEASE_BRANCH"

if [ "$DO_PR" -eq 0 ]; then
  cat <<EOF

  ${BOLD}Committed locally on $RELEASE_BRANCH. Nothing pushed.${RST}
      ./scripts/release.sh --version $NEW --pr        # push and open the PR
  To undo:
      git checkout $MAIN_BRANCH && git branch -D $RELEASE_BRANCH
EOF
  exit 0
fi

# ------------------------------------------------------------------ 8. push and PR ----
step "Pull request"
confirm "Push '$RELEASE_BRANCH' to origin and open a PR into $MAIN_BRANCH?"
git push -q --set-upstream origin "$RELEASE_BRANCH"
ok "pushed $RELEASE_BRANCH"

PR_URL=$(gh pr view "$RELEASE_BRANCH" --json url -q .url 2>/dev/null || true)
if [ -z "$PR_URL" ]; then
  PR_BODY=$(printf '%s\n\n---\nOpened by scripts/release.sh. Merging is gated on CI.\n' "$NOTES")
  PR_URL=$(gh pr create --base "$MAIN_BRANCH" --head "$RELEASE_BRANCH" \
    --title "Release $NEW" --body "$PR_BODY")
  ok "opened $PR_URL"
else
  note "PR already open: $PR_URL"
fi

if [ "$DO_RELEASE" -eq 0 ]; then
  cat <<EOF

  ${BOLD}PR is open. Nothing merged or published.${RST}
      $PR_URL

  CI is running against it now. Once it is green:
      ./scripts/release.sh --version $NEW --release   # merge, tag, publish
EOF
  exit 0
fi

# ------------------------------------------------------ 9. wait for CI, then merge ----
step "Waiting for CI"
note "the local gates above were a fast filter; this is the run that decides"
note "watching $PR_URL (timeout ${CI_TIMEOUT}s)"
if ! timeout "$CI_TIMEOUT" gh pr checks "$RELEASE_BRANCH" --watch --fail-fast; then
  die "CI is not green — the PR stays open and nothing was merged or published.
       Fix it, push to '$RELEASE_BRANCH', then re-run with --release."
fi
ok "CI passed"

step "Merge and tag"
confirm "Squash-merge $PR_URL into $MAIN_BRANCH, tag v$NEW and publish a GitHub Release?"
gh pr merge "$RELEASE_BRANCH" --squash --delete-branch \
  --subject "Release $NEW" --body "$(printf '%s' "$NOTES" | head -60)"
ok "squash-merged into $MAIN_BRANCH"

git checkout -q "$MAIN_BRANCH"
git pull -q --ff-only origin "$MAIN_BRANCH"
git tag -a "v$NEW" -m "revoice $NEW"
git push -q origin "v$NEW"
ok "tagged v$NEW on $(git rev-parse --short HEAD)"

# ------------------------------------------------------------- 10. GitHub Release ----
step "GitHub Release"
printf '%s\n' "$NOTES" > "$VERIFY_ENV/notes.md"
gh release create "v$NEW" --title "revoice $NEW" --notes-file "$VERIFY_ENV/notes.md" \
  dist/revoice-"$NEW"-*.whl dist/revoice-"$NEW".tar.gz >/dev/null
REL_URL=$(gh release view "v$NEW" --json url -q .url)
ok "published $REL_URL"
note "wheel and sdist are attached to it"
note "GitHub Pages rebuilds from pages/ on the merge commit"
printf "\n%sreleased revoice %s%s  %s\n" "$GRN$BOLD" "$NEW" "$RST" "$REL_URL"
