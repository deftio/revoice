# Changelog

## 0.1.10 - 2026-09-14

**Better metrics, under a hard constraint: everything here runs in a browser.**

A literature pass produced a reading list. Four items survived contact with the code and
with the fact that the compare page is served off GitHub Pages with no server to ask —
which rules out spaCy, sklearn and every embedding model. `voicemetric` stays stdlib-only
and every number below is asserted equal to its JavaScript port on shared fixtures.

### Added — the paired question (`revoice rewrite-score`)
`voicemetric/transfer.py`, ported to `pages/voicespace.js`, surfaced on the compare page.

Everything before this measured an **absolute** question — *is this text by X?* — and
measured it weakly: AUC ~0.69 across 70 authors with hard negatives. This asks the paired
one:

    Delta_style = D(source, target) - D(rewrite, target)

Source and rewrite share their topic, genre, era, length and content, so every confound
that makes the absolute question hard sits on **both sides of the subtraction and
cancels**. It is also the question revoice always had to answer: "this passage scores 43
against Twain" was never useful; "this rewrite moved 11 points toward Twain, and that
movement clears the noise" is.

Two axes, returned side by side and **never averaged**:
- `style` — signed movement with a bootstrap interval **on the movement**. `moved` is
  true only when the whole interval clears zero, so +9 with an interval of [-4, +21] is
  reported as *no measurable movement*.
- `meaning` — figures, proper nouns, negation, hedging, content words. It **vetoes**: a
  rewrite that moved 14 points toward the voice while dropping a third of the source's
  numbers has not half-succeeded. The score is the **minimum** across families, not the
  mean, because meaning is conjunctive and a mean hands that rewrite a comfortable 0.8.

Stated limit, in the output itself: *lexical retention, not entailment*. It catches what
a rewrite dropped or swapped; it cannot catch a reordering that keeps every token and
inverts the sense. `test_reordering_that_inverts_meaning_is_the_known_blind_spot` records
that as a property rather than leaving it to be discovered.

### Added — c@1, so an abstention can score
AUC and EER grade a *ranker*. This engine has to decide, and its most common **correct**
answer is "these intervals overlap, I cannot call it" — which neither measure can score
as anything but a coin flip, and which plain accuracy actively punishes. `verify.c_at_1`
(Peñas & Rodrigo 2011, the PAN verification measure) gives an abstention the accuracy you
achieved on what you did answer, so the only way to profit is to abstain on the cases you
would have got wrong. Reported per bench cell as `decision`, with the band that scored
best and the abstention rate it bought.

It immediately answered something the other measures could not — and the answer is not
flattering. Measured on the full 70-author corpus, 99,920 trials: at **50 and 100 words
the best abstention band is exactly zero**. Declining to answer never helps, because a
borderline score at that length is not a signal that the case is hard; it is just a
score. The composite has no self-knowledge below ~200 words. Above that it has a little,
and only a little: abstaining on ~8–9% of pairs buys between 0.1 and 0.9 points of
accuracy. AUC climbs smoothly from 0.565 to 0.780 across that whole range and is silent
about where in the climb the transition happens.

More uncomfortably, `vocab` — the component held out of the voice score *by construction*
because it measures subject matter — is better calibrated about its own reliability than
the voice composite is, at every length. That argues for calibration work (§6), not for
putting it back in the score.

### Fixed — `release.sh` died in CI, which is the one place it has to work
`actions/checkout` on a `pull_request` fetches only `refs/pull/N/merge` at depth 1: the
checkout is a detached HEAD with **no branches and no remote-tracking refs**. The script
required a local `main`, so in CI it died in preflight before reaching a single gate, and
took five of its own tests down with it. The release PR going red is how this surfaced.

The main branch is only needed to *publish* — it is the PR base. Verifying does not need
it, and now does not ask for it. Publishing from a detached HEAD is refused with the
checkout command.

**It took two attempts, for a reason worth recording.** The first fix accepted
`origin/main` as a fallback and was verified against a `git worktree` — which shares the
parent repository's refs, so `origin/main` was present and the reproduction passed while
CI kept failing. A worktree is not a fresh clone. The regression test now builds a
standalone repository with no branches and no remotes, which is what CI actually hands
you, and asserts the script reaches the gates rather than dying before them.

That fixture immediately found a second bug it had been hiding: `VAR=$(cmd)` under
`set -e` exits the script when `cmd` fails, so the branch added to *handle* a failing
check could never run — the script died with the raw exit status and printed nothing.
Both captures now suspend errexit and inspect the status themselves.

### Fixed — a construct bash 3.2 accepts and bash 5 rejects
`${#arr[@]}` on an empty array is an unbound-variable error under `set -u` on bash 3.2,
which is what macOS ships. The obvious guard, `${#arr[@]-0}`, is a **bad substitution**
on bash 5, which is what CI runs — `${#...}` takes no default. The script passed
`bash -n` locally and then died on the first line of its own reporting helper in CI,
taking every gate with it. The count is now a plain integer, correct on both.

Guarded two ways: a static check that forbids `${#array[@]}` with a default, and a
cross-check with any bash ≥ 4 on the machine, since `bash -n` only ever validates the
bash you happen to have. Verified by running the whole script under `bash:5` in a
container against a simulated CI checkout — detached HEAD, no branches, dirty tree,
existing tag, undated changelog — and confirming all three problems report correctly.

(The static check needed fixing too: its first version flagged the comment in the script
that documents this very pitfall. That is the third time this session a source-text scan
has matched the text explaining the thing it scans for.)

### Fixed — generated-file staleness could not be told apart from "cannot check here"
`bench-corpus/` is fetched data and gitignored, so a fresh clone does not have it and
`export_demo_baselines.py` silently falls back to `examples/voices` — 4 voices instead of
1,594 documents. `--check` then reported the committed `population.json` as **stale**,
and following its advice would have regenerated it from the fallback and committed a
materially different file. It now compares the source recorded in the file against what
the checkout actually has, exits 2 for "cannot verify here", and tells you to fetch the
corpus rather than to overwrite the file.


A GitHub Actions `pull_request` checkout is a **detached HEAD** at `refs/pull/N/merge`
with no local branches. The script required a local `main` to exist, so in CI it died in
preflight before reaching a single gate — and took five of its own tests down with it,
which is how this was found: the release PR's CI run went red.

The branch is now accepted as `main` *or* `origin/main`, and a detached HEAD is fine for
verifying. Only publishing needs a branch, and asking to publish from a detached HEAD is
refused with the checkout command. A regression test builds a real detached worktree and
drives the script through it.

### Fixed — `release.sh` ran CI's gates in an environment CI does not use
The test gate claimed to run "the same gates CI runs" while running them somewhere
else. `.github/workflows/ci.yml` does `uv sync --all-extras` and installs the test
tools first; the script did neither, so `tests/test_core_extra.py` exercised
`.docx`/`.pptx`/`.pdf` extraction with those libraries absent and failed three times for
a reason that had nothing to do with the release. The script now prepares the same
environment before testing.

That is not a breach of the read-only contract. The contract is about what gets
**committed and shipped** — no version bumps, no changelog edits, no regenerated site
data. `.venv/` is gitignored and is not part of what ships, and refusing to prepare it
meant the local gates quietly tested something other than what CI tests, which is the
exact failure the contract exists to prevent.

Also: the undated-changelog message suggested `sed -i ''`, which is correct on BSD and
broken on GNU. Suggesting a command that fails is worse than suggesting none, so the
script detects which `sed` is installed and emits that one.

### Changed — `release.sh` does the mechanical work instead of assigning it
The script refused `--release` with *"no 'main' branch here … Fetch it: `git fetch origin
main:main`"* — telling you to type a command it could have run, after several minutes of
building and testing, and then asking you to start again. That is not a gate, it is an
obstacle, and it is the opposite of walking someone through a release.

The distinction the script now draws is **decision vs work**:

- **Decisions stop it.** What version this is. What the release notes say. Whether the
  tests pass. Whether to publish. Nobody else can settle those.
- **Work it does**, echoing each command as `$ git branch main origin/main` so nothing
  it touches is a mystery. A missing local branch that exists on origin is one fetch.

`--fix` extends that to the two repairs that were previously homework: dating the
CHANGELOG heading (the date is today; there is nothing to choose) and regenerating the
derived site data. It commits **only the files it touched** — anything else you had open
stays yours, and is reported rather than swept into the commit. Writing the notes is
still a decision, so an empty section still stops the script.

Default behaviour is unchanged: without `--fix` nothing in the repository is written.
That contract used to be tested by grepping the source for `git commit` and `sed -i`,
which stopped meaning anything once a `--fix` mode legitimately ran them. It is now
tested by running the script against a repo with a repairable problem and asserting not
one byte moved — which is what the contract always actually said.

### Changed — `release.sh` now tells you what to type
Every gate that can refuse a release hands back the command that fixes it, and the
repo-state gates are collected so three problems take one run instead of three:

```
not ready to release — 3 thing(s) to do first:

1. v0.1.10 is already tagged — this version has shipped
       Bump to the next version and write its notes:
         $EDITOR revoice/__init__.py      # __version__ = "0.1.11"
         $EDITOR CHANGELOG.md             # add a '## 0.1.11 - 2026-09-15' section
         python scripts/export_demo_baselines.py
         git commit -am "Release 0.1.11"

2. the working tree has uncommitted changes (CI can only test what is committed)
          M CHANGELOG.md
         ?? scratch.tmp
       Commit them:
         git add -A && git commit -m "Release 0.1.10"
       or set them aside:
         git stash -u

3. CHANGELOG.md still marks 0.1.10 as (unreleased)
       Date the heading:
         sed -i '' 's/^## 0.1.10 (unreleased)$/## 0.1.10 - 2026-09-15/' CHANGELOG.md
         git commit -am "Release 0.1.10"

do them in order — a later step can depend on an earlier one.
then re-run: ./scripts/release.sh
```

The next version number is computed, today's date is substituted in, and the BSD/GNU
`sed -i` difference is noted, because that one bites everybody once. Missing tools give
their install line; `gh` unauthenticated gives `gh auth login`.

Test and build failures stay one at a time — those are not fixed by typing a command,
and running the rest of the suite after the first failure buries the output you need.
What each gives you is the **un-quieted** command that reproduces it, since the script
runs them with `--quiet` and re-running the same silenced command shows nothing.

Three tests keep this honest: one asserts three simultaneous problems produce three
numbered items in one pass, one asserts the undated-changelog message contains a
runnable `sed` line with today's date already in it, and one parses every `need` call in
the script and fails if any message states a problem without offering something to type.

One knock-on: the read-only guard scanned the source for `git commit`, `sed -i` and
friends, and the new messages legitimately contain those as *text to show the user*. It
now strips double-quoted spans before scanning — an instruction is quoted, a real write
would not be — with a companion test proving the strip has not defanged it.

### Added — `pages/report.html`, and a Markdown export
The browser twin of `revoice space --report`. compare.html answers *did this text drift
from that one*; this answers *of these several samples, which sit closest to this voice,
and is that ordering worth anything*.

The second half of that question is the design. A ranked list invites the order to be
read as the result, and on this measure the order is very often noise — two samples can
differ by 9 points and share 14 points of interval. So the page draws every reading and
its interval on one scale, states the worst overlap **in words** before anything is
ranked, and only then shows the axes. The verdict is plain: *"The ranking above is not
evidence. Hand this page a different few pages of the same documents and the order could
flip."*

**Markdown export**, by download or copy, and `revoice space --report out.md` writes the
same document — the suffix picks the format. It is not a transcription of the HTML: the
page can *draw* an interval and plain text cannot, so the Markdown leads with the overlap
in words, repeats the interval in every table row so no number ever appears without one,
and carries its own limits section, because someone will paste it into a pull request
where nobody has read `docs/metrics.md`.

`tests/test_pages_parity.py` asserts the page's export and the CLI's output are identical
strings. That caught two things the eye would not: an exactly-touching pair of intervals
reported as *"clear by −0.0 points"* — nonsense in both implementations, and formatted
differently by each, since Python prints negative zero and JavaScript's `toFixed` does not
— and a straight apostrophe against a curly one. The first is now a third case with its
own wording.

### Changed — one engine, not three
The browser had its own stylometry and it had drifted badly. `pages/stylometry.js` began
as "a JS port of the demo subset"; Python was then refitted three times and grew six
components; nothing compared them. `scripts/export_demo_baselines.py` carried a *third*
copy, under a docstring that said "keep the weights in sync". They were not in sync:

| | Python (fitted) | page (hand-typed) |
|---|---|---|
| components | 10 | 4 |
| `ngram` | 0.181 | **0.600** |
| `punct` | 0.332 | 0.100 |
| `rhythm` | **0.000** (measured as noise) | 0.100 |
| `richness`, `structure` | 0.104, 0.064 | absent |

Measured on 112 trials across 28 authors: Python **AUC 0.793**, the page **0.688**, and
the sigma the page led with **0.662**. On one case it inverted outright — it ranked
Twain's own other work as *less* like Twain than Bret Harte.

Now there is one engine. **`pages/voicemetric.js`** is a full port of `features.py` +
`baseline.py` and agrees with the Python composite on **112 of 112 trials**, AUC 0.793 to
0.793. `stylometry.js` is deleted; `export_demo_baselines.py` calls the real
`baseline_from_texts` / `score_text`.

**What keeps it ported**, since asking people to remember plainly did not:

- **Data is generated.** `pages/engine-constants.js` is written out of Python by
  `export_demo_baselines.py` — every word list, bin edge, weight, axis, punctuation set.
  `voicespace.js` was migrated onto it too, so nothing on either side is hand-typed data.
  A generated constant cannot be edited into disagreement, and hand-copied data is what
  actually drifted.
- **Algorithms are tested.** `tests/test_pages_parity.py` runs the real JavaScript under
  node against the real Python on corpus fixtures: all 29 fingerprint fields, the
  composite, all ten components, the weights, every generated constant, and a staleness
  check that regenerating is a no-op.
- **New code cannot skip the net.** `test_every_ported_function_has_a_python_counterpart_under_test`
  enumerates the JS exports and fails on any that is neither paired with a Python
  function nor declared page-only below an explicit marker.

Agreement is to a stated tolerance per family, not bit-exact. The residual is rounding —
Python breaks exact ties to even, JavaScript away from zero, and `fingerprint()` rounds
~25 values, so a ratio like 1/32 differs in the fourth place. Emulating that costs real
complexity in the hot path and is invisible against a composite reported to one decimal.
A *missing component or a wrong weight* moves a composite by whole points, and that is
what the tolerances forbid.

`pages/compare.html` now shows all ten components with the weight each carries, so a
family the bench fitted to zero reads as `0.000 · noise` rather than being quietly
dropped, and the "biggest movement" line ignores families that carry no weight.

### Added — `bench.interval_coverage`, which tests the part we trusted most
Every report here leads with a confidence interval, and this project's whole argument for
them is that a bare number invites a decision it cannot support. That argument is worth
exactly as much as the interval's coverage, and coverage had never been measured. It is
now, on 841 documents:

- **On differences — calibrated.** Split a document's windows into halves whose true
  difference is zero by construction, bootstrap that difference the way `style_delta`
  does, and the 90% interval contains zero **91.6%** of the time (95% → 95.8%). The
  construction behind the rail, the `moved` verdict and `rewrite-score` holds up.
- **On absolute levels — thin-tailed.** Error is ~0 at the median and grows with the
  level: a nominal 95% interval behaves like **86%**. Misses are one-sided, **205 above
  the band against 74 below**, so the *upper* edge of a similarity interval is not a bound
  to lean on. "This is clearly not a match" is the claim to distrust first.
- **Cllr_cal is ~0.007** — essentially none of the Cllr cost is miscalibration. The scores
  are well-calibrated statements of near-ignorance, which is the good version of a bad
  number. It also means the whole prize is in discrimination, not calibration.

Not fixed: BCa would be the standard remedy for the skew, and applying it moves every
published interval. The finding goes in the record first.

Writing the test wrong was itself instructive. The intuitive version — build the interval
from half A, check whether half B's reading lands in it — is **pessimistic by √2**,
because A's band carries A's noise while B's point carries its own. A perfectly calibrated
90% interval scores 0.755 on it. The first run looked like a 19-point overconfidence
scandal and was mostly test geometry; `_normal_pair_expectation` now prints the corrected
benchmark beside the observed number so nobody repeats the mistake.

### Fixed — a claim this package made about itself
`yules_k` asserted, in its own docstring and with no source, that Yule's K "does NOT
drift with text length". **Tweedie & Baayen (1998)** measured that whole family of
richness constants and found none of them constant. K is far steadier than TTR, which is
why it is the one used here, but "more stable" was the honest claim and
"length-independent" was not. Corrected in the docstring and in the browser port.

`bench.length_sensitivity` now measures the drift instead of anyone asserting its
absence: truncate one document to each length in the grid, read the axes off each, and
report how far each moved when *only the amount of text* changed.

### Found — two axes running dead in the bench
The new diagnostic's first run, against a claim nobody had made. `bench._window` builds a
trial by `" ".join(words[start:start+n])`, which destroys every paragraph break, so every
trial text is exactly one paragraph. `paragraph_length` and `sentences_per_paragraph` are
then pure functions of the query length (r = **0.91**), identical for target and
non-target within a length cell. They cannot inflate AUC — a constant discriminates
nothing — but they are dead weight in the `structure` component, diluting the signal it
does carry. Cut on paragraph boundaries instead, as `space.windows` does for the page,
and r drops to **0.09**; hence the two `cut` modes, and why conflating them is how a dead
axis goes unnoticed.

Yule's K itself came out better than feared and worse than claimed: near-zero correlation
with log length (r = 0.05-0.13) but **~0.5 population standard deviations** of drift
across the grid, because the movement is not monotonic in log n and correlation alone
would have exonerated it. Recorded, not fixed — fixing it moves scores and therefore
`signature()`.

### Fixed — two bugs in the new code, found by its own tests
- `_stem` split one word three ways: "measured" lost its "ed" and became `measur` while
  "measure" kept its "e" and stayed whole, so a rewrite that changed tense read as a lost
  content word.
- `_entities` counted the first word inside a quotation as a proper noun, so every line
  of dialogue donated one.

### Changed
- `voicemetric` 0.4.0 → **0.5.0**, and `signature()` is **unchanged** — the first release
  where the version moved and the signature did not. Nothing here shifts an existing
  number, so 0.4.0 and 0.5.0 scores stay comparable. That is the distinction the
  signature exists to draw.
- `pages/compare.html` takes an optional third box, the original draft. Fill it and the
  page leads with the paired reading instead of the absolute one.
- Citations added for the measures that were already implemented (Stamatatos 2009,
  Sapkota et al. 2015). One item was deliberately **not** cited: a 2025 EMNLP Findings
  paper on LLM imitation of everyday writing styles, whose every source URL carried
  `utm_source=chatgpt.com` — it came out of a chat session, not a literature search, and
  this project does not cite what it has not checked. If it holds up, its *dataset*
  matters more than its result: our whole benchmark is 19th-century published prose, and
  a personal-voice tool validated on dead novelists has a blind spot no feature closes.

## 0.1.9 (unreleased)

**The report the site and the tool both wanted.**

### Added
- **`revoice space --report out.html`** — the full standalone report, from the local
  tool, for any number of samples against one voice:

  ```bash
  revoice space bench-corpus --against twain \
    -t sample-a.md -t sample-b.md -t sample-c.md --report report.html
  ```

  `--text` is now repeatable. `chart.report()` builds it: masthead, the overlap rail,
  a per-sample axis chart, and the method notes. Self-contained — no scripts, no network,
  no fonts to fetch; it opens from a file, in an email, or in five years.
- **The overlap rail**, in both the Python report and the compare page. Every reading on
  ONE 0–100 scale with its interval drawn at the same weight as the estimate, plus
  `chart.overlap()` / `chart.worst_overlap()` naming the least defensible comparison in
  words. It is the piece a single chart cannot show, and it was the one part of the
  hand-built prototype that had never made it into the codebase.
- The CLI prints the same warning the rail does: *"closest pair overlaps by 13.2 points —
  that ordering is not evidence"*, so nobody reads two numbers off stdout and draws a
  conclusion the intervals forbid.
- `pages/compare.html` now leads with the rail: the reference's own passages against the
  candidate, which makes the page answer the question it should — *is this distinguishable
  from how much the reference already varies on its own?*

### Fixed — two ways the rail lied before it was right
Both produced a confident result that was pure methodology, and both were visible only
because putting the readings on one scale made them comparable:
- The reference's windows were scored leave-one-out (each against the other N−1) while
  the candidate was scored against all N. The reference was handicapped and looked *less*
  like itself than a stranger did.
- The reference was scored per window (~300 words) while the candidate was scored whole
  (~600+). Longer text has steadier coordinates and sits closer to any centroid, so the
  candidate won on length alone.

  Now every held-out reference window builds the same reduced region, and both that
  window and each candidate *window* are scored against it: same reference size, same
  construction, same text length on both sides. With that fixed, Twain-vs-Twain and
  Twain-vs-Darwin both come back overlapping — which is the honest answer at AUC 0.69,
  and much better than confidently asserting something false.

## 0.1.8 (unreleased)

**The site shows the real metric; there is now one command to ship it.**

### Added
- **`scripts/release.sh`** — ships what is already committed. It **writes nothing to the
  repository**: no version bump, no changelog edit, no regeneration. Preparing a release
  is normal work you commit; releasing is mechanical and separate, so the commit CI
  validates is byte-for-byte the commit that gets tagged and published.
  - `./scripts/release.sh` verifies, tests and builds, touching nothing. `--pr` pushes
    the branch and opens a PR. `--release` waits for CI, squash-merges, tags, and
    publishes a GitHub Release with the wheel and sdist attached. `--pypi` is opt-in.
  - **`--release` blocks on the CI run GitHub performs against the PR**, not on the local
    checks. Those are a fast filter; a release whose only evidence is "it passed on my
    laptop" is the thing this prevents. Red CI leaves the PR open and publishes nothing.
  - Refuses a dirty tree, a reused tag, a version the CHANGELOG has no dated notes for,
    and stale generated site files.
- **The version now lives in exactly one place**: `__version__` in `revoice/__init__.py`.
  `pyproject.toml` declares `dynamic = ["version"]` and reads that attribute, so the
  packaged metadata cannot disagree with the running code, and the site, docs and release
  tag all derive from the same line. A version written twice is one that will eventually
  be wrong in one of them, silently.
- `revoice.version()`, matching `rubric.version()` and `voicemetric.version()`.
- `scripts/export_demo_baselines.py --check` — verifies the generated site files are
  current without writing, so the release can check rather than mutate.
- `tests/test_release_script.py` — the guards, plus assertions read from the script's
  own source that it cannot push without `--push` and never runs fewer gates than CI.
- `CONTRIBUTING.md` documents the release flow, including that the two engine versions
  are bumped by hand and deliberately not touched by the release script.

### Added (site)
- `pages/voicespace.js` — a browser port of `voicemetric.space` and `chart.py`. The
  compare page builds its reference from text the reader pastes in, so the measurement
  has to run client-side; there is no server to ask.
- **The compare tab now renders the full 17-axis chart** — per-axis bars with direction,
  bootstrap whiskers, and the overall similarity with its interval — replacing the
  four-row component table.
- `pages/demo/population.json` — the reference population (17 axes × mean/sd, ~1 KB,
  fitted on the 1,594-document benchmark corpus), exported by
  `scripts/export_demo_baselines.py`. Without it the page would have to treat whatever
  was pasted in as its own definition of typical prose, which puts every coordinate near
  zero and makes the chart say nothing.
- `pages/version.js` — generated, so it cannot drift: the nav prints
  `revoice 0.1.8` in small print, with voicemetric's version and signature and rubric's
  version on hover, and the footer carries all three.
- `tests/test_pages_parity.py` — runs the page's actual JavaScript under node against
  the Python engine on shared fixtures. **They agree exactly**, not approximately: the
  JS rounds where the fingerprint rounds, so the tolerance is 1e-9 rather than something
  loose enough to hide the drift the test exists to catch. Also checks the shipped
  population matches the current axis set, that `version.js` matches the installed
  packages, and that every page loads it *before* `site.js`.
- CI installs node, because these tests skip without it and a silent skip is exactly how
  two implementations of one measurement drift apart.

### Why a second implementation at all
Two copies of a measurement is a real cost, taken deliberately: the alternative is a
compare page that either needs a backend or shows something weaker than the tool does.
The parity test is what makes it affordable — a divergence is a failing build rather
than a discrepancy someone notices months later by hand.

## 0.1.7 (unreleased)

**Both engines are versioned, and revoice records which build produced a number.**

### Added
- `rubric.version()` / `voicemetric.version()`, plus `describe()` on both — a clean,
  JSON-safe API surface for a caller to record alongside any result.
- **`voicemetric.signature()`** — a short hash over everything that changes a score:
  components, weights, axis names, span-calibration buckets. This is the part that
  matters. The composite weights have been refitted three times, each refit silently
  changing every score computed against an existing baseline, and **not one of them
  moved a function signature**. A release number would have said nothing.
- **`rubric.rubric_signature(rubrics)`** — the analogue for judging, where the numbers
  come from the caller's YAML rather than the engine. Covers choice names, score
  mappings, weights and reject thresholds; deliberately ignores descriptions, so
  rewording one for clarity does not invalidate a run.
- `judge_all` now returns `"engine"` with the version and spec signature, so a stored
  judgment carries its own provenance.
- `learn` stamps `voicemetric.describe()` into `params/baselines.json`,
  `params/calibration.json` and the pack manifest; `metrics.engine_of(pack)` reads it
  back. **`revoice status <voice>` warns when a pack was built under a different
  signature** — its stored calibration bands are measuring something subtly different
  from anything computed today. `revoice doctor` prints both engines up front.
- `tests/test_engine_versions.py` — the contract for both engines, including that a
  weight refit moves the signature, that cosmetic rubric edits do not, and that the
  stale-pack warning actually fires.

### Versions
`rubric` **1.0.0** — the contract (model classifies, code computes) has not changed and
is not expected to. `voicemetric` **0.4.0** — pre-1.0 on purpose: MINOR means *the
numbers changed*, and they still do.

### Documentation
- Both packages' READMEs now cover install / build / test / versioning, and state
  plainly what each is and is not good for. `voicemetric`'s records the measured
  ceiling (AUC ≈ 0.69, by genre) rather than leaving a reader to assume more.

### Fixed
- `load_baselines` / `load_calibration` strip the `_engine` stamp, so no caller can
  mistake it for a register. The stamp sits alongside the register keys rather than
  nesting the data a level deeper, which keeps every existing reader working.
- `cwd` / `learned_cwd` fixtures moved to `conftest.py` now that more than one test
  module needs a working directory with a learned pack.

## 0.1.6 (unreleased)

**The voice-similarity engine becomes a standalone package.**

### Changed
- New package **`revoice/voicemetric/`** — sibling to `revoice/rubric/`, same division of
  labour. 2,400 lines of measurement that imports **nothing from the rest of revoice**
  and depends on **nothing outside the standard library**.

  ```
  features.py   deterministic stylometry
  baseline.py   corpus baselines, composite score, span-length calibration
  space.py      17 named axes, voice regions, bootstrap intervals, dimensionality
  chart.py      the report as dependency-free SVG
  verify.py     AUC, EER, PAV, Cllr, weight fitting
  bench.py      authorship-verification harness
  ```

  Moved from `core/`: `stylometry.py`→`features.py`, `verify.py`, `bench.py`,
  `voicespace.py`→`space.py`, `voicechart.py`→`chart.py`, and the generic half of
  `metrics.py`→`baseline.py`.

- **The two couplings that blocked this are inverted.** `metrics` no longer takes a
  `VoicePack` (it takes texts; `calibration_from_texts` replaces the pack-aware
  `build_calibration`), and `bench.load_corpus` takes an injected `read` callable
  instead of importing revoice's `ingest`. `revoice/core/metrics.py` is now purely the
  seam: read a pack's corpus, hand texts to the engine, write results back.

- Every import site elsewhere in revoice was updated; nothing else changed behaviour.

### Added
- `revoice/voicemetric/README.md` — what it measures, what it is honestly good at
  (register drift), and what it is not (an authorship test), with the measured ceiling.
- `tests/test_package_boundaries.py` — enforces the boundary for **both** standalone
  packages by parsing the AST, so an import added inside a function body is caught as
  surely as one at the top of a file. Also checks each package ships a README, that
  `__all__` fully resolves, and that no source under `voicemetric/` so much as mentions
  `VoicePack`.
- `voicemetric.bench.read_text_file` — the default reader rejects binary **by content**
  (NUL bytes, or a decode needing >0.5% replacement characters) rather than by
  extension. Sniffing content is the right amount of knowledge for this layer: it keeps
  a stray image out of a corpus without the measurement code learning what a `.docx` is.

### Why now
Both `rubric` (how good is this writing?) and `voicemetric` (whose writing is this?)
have to work before any revoice quality claim means anything. Making the boundary real
now keeps them independently testable — and, if either is ever more useful outside
revoice than in it, the lift is already done.

## 0.1.5 (unreleased)

**Similarity you can read and argue with: per-axis, with a confidence interval.**

### Added
- `voicespace.similarity_report()` — overall and per-axis similarity to a voice, each
  with a **bootstrap confidence interval** over the document's own paragraph windows.
  Answers "how much would this move on a different few pages of the same document",
  which is the question a bare score silently skips. Under three windows it reports no
  interval rather than inventing one.
- `revoice/core/voicechart.py` + `revoice space --svg` — a dependency-free SVG report:
  per-axis bars (length = size of difference, side = direction), whiskers for the
  interval, numbers printed as well as drawn. Colours are CSS custom properties with
  literal fallbacks, so one generator serves a standalone `.svg` and an inline embed in
  a themed page.
- `revoice space --text X --against Y` now prints the similarity, its interval, and the
  axes that differ most — and warns explicitly when a text is too short to have an
  interval at all.

### Why it matters
Against a Twain reference: held-out Twain **45.9 [31.9–49.1]**, Bret Harte
**37.2 [25.2–45.9]**, a Federal Register rule **24.5 [18.7–29.8]**. The 8.7-point gap
between the two authors reads as decisive; their intervals overlap across **14 points**,
so the ordering is not evidence. The regulatory sample separates cleanly. Confident
about register, weak about authorship — which is what AUC 0.69 looks like on one
document, and invisible without the interval.

### Fixed
- `VoiceRegion.spread` now floors at 0.15 population standard deviations. A voice fitted
  on near-identical reference texts previously got a spread near zero, so deviations
  divided by it returned in the millions and every per-axis similarity underflowed to
  exactly zero.

## 0.1.4 (unreleased)

**Voice becomes a vector with named axes, and the benchmark gains modern document types.**

### Added — voice space
- `revoice/core/voicespace.py` + **`revoice space`**: writing style as **17 named,
  interpretable axes** (sentence length, subordination, nominalisation, punctuation
  variety, formality, person, paragraph shape...) rather than a single similarity score.
  Coordinates are z-scored against a reference population, so `+1.4 on subordination`
  means "1.4 sd more subordinate than typical prose" — a claim a reader can check. A
  voice is a *region* (centroid + spread); two voices compare directly without electing
  one as the baseline; and a distance decomposes into *which axes differ and by how much*.
- **It is more discriminative, not just more legible.** Same protocol as the scalar
  benchmark (70 authors, work-level LOO, hard negatives): voice-space distance scores
  **AUC 0.689–0.699 against 0.652** for the fitted nine-component scalar composite. The
  best single interpretable axis (`readability`, 0.706) matches the whole composite.
- **Effective dimensionality: ~7.8 of 17 axes** (top factor 28% of variance). The axes
  are correlated, so the labels overstate how many independent things voice is — a useful
  brake on feature-set sprawl — but no single "general style factor" dominates either.

### Added — the register corpus
- `scripts/fetch_register_corpus.py`: **140 documents across five modern document
  types** — encyclopedic (Wikipedia, CC BY-SA), scientific articles (Europe PMC, CC BY),
  regulatory notices (US Federal Register, PD), technical reports (NASA NTRS, PD) and
  press releases (NASA, PD). Provenance and licence recorded per document.
- Kept **separate from the authorship corpus on purpose**: these are institutional or
  multi-author documents and cannot be authorship positives without lying about who
  wrote them. They serve register measurement, which is revoice's other stated job.
- On "marketing brief": no public-domain corpus of modern marketing copy exists.
  Agency press releases are the closest honest analogue — institutional promotional
  prose — and are labelled as such rather than dressed up.

### What the register corpus shows
- Modern functional registers occupy one corner of the voice space: long words, heavy
  nominalisation, low readability, almost no first or second person.
- **19th-century technical prose sits closer to comic writing (0.42) than to modern
  technical reports (0.91).** The instructional register moved a long way in a century,
  so the Gutenberg `technical` group is a poor proxy for how revoice's users write.
- Adding these registers raises measured effective dimensionality 7.77 -> 8.2: modern
  functional prose exercises axes 19th-century books leave flat.

### Fixed
- **The eigen-solver was wrong**, caught by a known-answer test. Naive power iteration
  with deflation restarted from the same vector, which after deflation lies in the null
  space — the identity matrix returned `[1, 0, 0, 0]` instead of `[1, 1, 1, 1]`. Fixed by
  retaining eigenvectors and projecting them out, with basis-vector starts: a smooth
  start like `sin(c + i*d)` spans only a two-parameter family and stalls after two
  deflations.
- One global length floor in the register fetcher silently reduced `technical_report`
  to three documents (NASA abstracts run 400-1500 characters). Floors are now
  per-register. A short register is honest; one that vanished to a constant is a bug.

## 0.1.3 (unreleased)

**A benchmark corpus big enough to trust, and the prior art we should have read first.**

### Added
- **The evaluation corpus grew from 8 authors to 70**: `scripts/fetch_bench_corpus.py`
  now builds **1,594 samples across 70 authors and 11 genres** (~15 MB) from
  public-domain Gutenberg texts — humor, science, technical, philosophy, history,
  economics, fiction, adventure, essay, travel, children's. Within a genre the authors
  share era and register, so telling them apart is authorship and nothing else.
- **A `technical` group — instructional and product literature.** Manuals, trade
  primers, field guides, clinical and cookery writing: Morgan's *Wireless Telegraph
  Construction for Amateurs*, Hawkins' *Electrical Guide*, Hamilton's printing-trade
  primers, Wheatley's *How to Make an Index*. This register is essentially absent from
  the standard corpora (CCAT50, IMDb62, Blogs50 are modern short-form web and news) and
  it is the one revoice's users actually write in.
- `revoice bench --hard-negatives` — draw different-author trials only from the same
  genre. On a multi-genre corpus the default mixes in easy cross-genre pairs, and
  separating a cookery manual from an adventure novel is not authorship attribution.
  Valla reports that hard-negative mining is what makes verification methods
  competitive with attribution methods.
- Per-genre breakdown in the bench report (`by_register`): authorship is not equally
  hard everywhere, and the spread is more useful than one aggregate.
- `tests/test_fetch_corpus.py` — the corpus builder's filtering logic, which is where a
  mistake silently poisons every downstream number.

### Changed
- The corpus builder is **catalogue-driven, not API-driven**: one static ~20 MB CSV from
  Gutenberg instead of 70 gutendex calls. Gutendex went fully unreachable mid-build;
  70 authors is 70 chances to fail, an offline join has none.

### Fixed — four corpus bugs, each of which looked like a metric failure
- **Substring name matching.** "Whittier, John Greenleaf" matched *John Richard Green*:
  58 works by the wrong man filed under one author label.
- **Non-positional given names.** "Smith, George Adam" (the biblical scholar) was filed
  as *Adam Smith* the economist, and "Bates, Walter" as *Henry Walter Bates*. Given
  names are now matched positionally against the catalogue's own first given name.
- **`\bautobiograph\b` never matches "Autobiography"** — there is no word boundary
  before the "y" — so the compilation blocklist silently passed everything it was
  written to exclude.
- **Volumes counted as independent works.** *Complete Writings* Vols 1-3 were three
  "works", which reinstated exactly the topic leak work-level leave-one-out exists to
  remove.

  Together these matter as much as any scoring change: the first naturalist build scored
  AUC 0.543 and the second 0.592 — same metric, cleaner corpus.

### Measured on the new corpus
- **Composite AUC 0.652** with hard negatives across 70 authors / 11 genres (5,016
  trials). Difficulty is strongly genre-dependent — humor 0.693, **technical 0.674**,
  down to philosophy 0.553. The `technical` group has the best operating point of any
  genre (0.296 TPR at 5% FPR), which is the good news: instructional and product prose
  carries more personal surface habit than literary fiction, and it is the register
  revoice's users actually write in.
- **The 0.1.2 weights were overfitted and the bigger corpus caught it.** Fitted on four
  humorists they scored 0.631 on the 70-author corpus — *below plain equal weighting at
  0.648*. Refitted across all genres: `punct .332 · delta .318 · ngram .181 ·
  richness .104 · structure .064`, the rest zero. `ngram` earns weight back once the
  corpus is broad enough that it cannot memorise one genre's vocabulary. Fitting on one
  genre buys performance there and loses it everywhere else.

### Research (docs/metrics.md 2.2b)
- **Valla** (Tyo, Dhingra & Lipton, IJCNLP-AACL 2023) is the closest prior art to
  `revoice bench` — standardised splits, cross-topic/cross-genre challenge sets, and its
  own Gutenberg dataset. Its finding that **a traditional n-gram model beats BERT on 5 of
  7 attribution tasks** (76.5% vs 66.7%) makes the embedding tier less of a foregone
  conclusion than the STEB rankings suggested, and its n-gram baseline is a
  *discriminative per-author classifier* rather than a distance to a centroid — a
  different shape from what revoice does, and now buildable given a background pool.
- **General Imposters** (Koppel & Winter; Kestemont et al.; shipped in `stylo`) is the
  most directly adoptable idea available: instead of "are these similar?", ask "are they
  more similar to each other than to a pool of imposters, across many randomly impaired
  feature spaces?" It yields a score in [0,1] with a real meaning and an explicit
  "don't know" band — which is precisely the failure mode our raw similarity keeps
  hitting — and it needs only the background pool the corpus builder now produces.

## 0.1.2 (unreleased)

**The metric was rebuilt against a corpus that can actually test it.** 0.1.1 shipped the
bench; this release acts on what it said. Three of the four findings contradict what the
bundled Twain/Darwin packs had suggested, which is the point of having built the harness.

### Added
- `scripts/fetch_bench_corpus.py` — assembles the topic-controlled evaluation corpus from
  public-domain Gutenberg texts: four 19th-c American humorists (Twain, Harte, Ward, Nye)
  and four naturalists (Darwin, Wallace, Huxley, Bates), three works each. Same era, same
  genre within a group, so telling them apart is authorship and nothing else. Written to a
  gitignored `bench-corpus/`; filters out compilations, correspondence and biographies,
  whose prose is not reliably the named author's.
- `revoice bench --fit` — fits component weights with a penalised multivariate logistic
  model on half the reference models and reports a held-out score, so the weighting is
  measured rather than argued about. `verify.fit_weights` is the (dependency-free) fitter.
- Nine separately-ablatable score components in place of six, all content-independent
  additions: function-word bigrams, sentence-opener class distribution, paragraph-shape
  statistics (the structural Writeprints family, previously absent entirely), punctuation
  ratios, contraction/hyphenation rates, parser-free syntactic proxies.
- `metrics.VOICE_COMPONENTS` — the components eligible for an authorship score. `vocab`
  is excluded **by construction**: measured, it is the best component on every corpus we
  have, and that is exactly the problem.

### Changed
- **Default weights are now fitted, not hand-picked**: `punct .392 · delta .258 ·
  syntax .197 · richness .069 · fwbigram .033 · opener .032 · structure .020`, with
  `ngram` and `rhythm` at zero. On the controlled corpus this scores macro AUC 0.677
  against 0.599 for the old hand-picked weights — which had themselves lost to plain
  equal weighting (0.649).
- **Character n-grams dropped to zero weight.** They were the strongest component on
  Twain-vs-Darwin (0.686) and near chance against same-genre contemporaries (0.578):
  they had been reading genre and subject, not authorship. Burrows' Delta and punctuation
  habits — content-independent by construction — carry the score instead.
- `type_token_ratio` and `hapax_ratio` removed from scoring; both fall as a text grows.
  **Yule's K** and **MTLD** replace them, both length-stable by design.
- Calibration is leave-one-out and bucketed by span length, with buckets sampled across
  their ranges. The bands make the old units error plain: 30.2 for a 25-40 word span
  against 50.7 for a whole document.
- `--strength` now sets how far below the band a span may sit before it is rewritten,
  so the dial controls a measured operating curve.

### Fixed
- **Minimal-touch.** The pipeline compared a paragraph's score against a band measured on
  whole documents. With length-matched bands, the fraction of the author's own text
  rewritten falls from **79% to 11%** at the default strength, with 51% of foreign text
  still caught. Where no span band exists the pipeline now declines to judge and passes
  the span through — leaving rough text in is the cheap error.
- `preflight` used the same stale document-level band; it now uses the length-matched one.
- `extract_text` returns None for a missing file instead of raising. The corpus index is
  a cache keyed by path, so a document deleted between `learn` runs would crash
  `train prep`.
- Report and CLI rendering enumerate components generically instead of hard-coding six
  names.

### Known limits
- On the naturalist group every component sits near chance. Victorian scientific prose by
  four contemporaries may simply be near-uniform in surface form, and Bates contributes
  only one work; this is the honest ceiling of the current feature set, and the argument
  for the embedding tier in `docs/metrics.md` §3.
- The test fixture pack was three ~30-word documents, which produced no span bands at all
  and hid the attribution path entirely. It is now eight documents of varied content in
  one voice.

## 0.1.1 (unreleased)

**The voice metric is now measured.** Everything revoice decides rests on one classifier
question — *is this passage already in the target voice?* — and nothing had ever tested it.
This release adds the instrument, and reports what it says.

### Added
- `revoice bench` + `revoice/core/bench.py` — an authorship-verification harness for the
  voice metric. **No LLM, no new dependencies**, deterministic given a seed. Reports AUC
  per query length, forensic calibration (Cllr / Cllr_min / Cllr_cal), the `tpr@fpr`
  operating point, a per-component ablation, a topic control, and a plain-language verdict.
  Corpus layout is a voice pack's, so `examples/voices` benches as-is.
- `revoice/core/verify.py` — verification statistics in pure stdlib: AUC (Mann-Whitney with
  tie handling), interpolated EER, `tpr_at_fpr`, PAV isotonic regression, Cllr with
  cross-validated logistic calibration. Known-answer tested against hand-derivable values.
- `metrics.baseline_from_texts()` — build a baseline from plain texts, so `learn` and the
  bench share one code path instead of two that drift.
- [`docs/metrics.md`](docs/metrics.md) — the voice-metric design doc: measurements, a survey
  of the authorship-verification literature (Cosine Delta, Writeprints, LUAR, StyleDistance,
  STEL-or-Content, forensic likelihood ratios), a three-space design, measured dependency
  tiers, and the sequencing that follows.

### What the measurements say
Under a topic-controlled protocol on the bundled packs, the shipped composite scores
**AUC 0.650** and **Cllr 0.941** (1.0 = a system that always answers "don't know"), and at a
5% false-positive rate keeps **14%** of the author's own text untouched. The `vocab`
component beats the whole composite and loses 0.162 AUC under topic control — it is largely
reading subject matter; `rhythm`, `delta` and `punct` sit near chance. Separately, the span
attribution threshold is calibrated in document-level units and applied to spans, so **79% of
the author's own paragraphs are classified "rewrite"**. The composite is not yet fit for the
decision the pipeline makes with it; `stats` output and the demo site should be read with
that in mind until it is fixed.

### Site (GitHub Pages)
- **The demo and compare pages were overclaiming and are now honest.** `compare.html`
  previously rated Darwin as "statistically indistinguishable" from Twain while rating
  Twain's own other work as "a reader may notice the difference" — a full inversion. Both
  pages now state what the measure does (register-drift detection), what it cannot do
  (authorship), and the measured error rate, on the first screen.
- `demo.html`'s two sample buttons fed back text that is **verbatim in the corpus that
  built the baselines** — visitors were watching memorisation. Samples are now labelled by
  provenance and a genuinely held-out Twain passage ships alongside them.
- Results report the **margin over the runner-up**, so a 2-point win across four baselines
  reads as "no real winner" rather than as an answer.
- Browser scoring weights are now chosen by `revoice bench` rather than by hand:
  `ngram .6 / delta .2 / rhythm .1 / punct .1` scores macro AUC 0.687 / EER 0.367 against
  0.641 / 0.401 for the previous even split. `pages/stylometry.js` and
  `scripts/export_demo_baselines.py` share the weights and both self-calibrate
  leave-one-out; `compare.html` reports a z-score against the reference's own variation
  instead of a percentage of it, which saturated.

### Site (bitwrench usage)
- The pages used bitwrench as a hyperscript renderer and almost nothing else: across six
  pages it called `bw.makeCard` exactly once out of 47 available components, and
  hand-defined `.bw_card` / `.bw_btn` / `.bw_table` — class names that look like
  bitwrench's but are not (BCCL emits `bw_bccl_*`), so every one had to be restyled from
  scratch with hard-coded hex.
- Now: real components throughout (`makeCard`, `makeTable`, `makeAlert`, `makeProgress`,
  `makeStatCard`, `makeFormGroup`, `makeTextarea`, `makeButton`, `makeButtonGroup`,
  `makeSpinner`), interactive regions as stateful TACOs (`o.state` + `o.render` +
  `bw.refresh`) rather than rebuilding result blocks by hand, `bw.responsive()` in place of
  hand-written `@media`, and every colour derived from `loadStyles().palette` and
  `.layout` tokens so the site re-themes from two seeds. `site.js` owns theming; pages no
  longer call `loadStyles` themselves.

### Fixed
- `eer()` interpolates the ROC crossing instead of taking the best corner, which reported
  1.0 for an uninformative system whose true EER is 0.5.
- `build_baselines` no longer emits a degenerate baseline (empty n-gram and tf-idf centroids)
  for a register whose files have become unreadable; the register is skipped instead.

### Changed
- `docs/architecture.md` "Voice-match metrics" now points at `docs/metrics.md` and states
  plainly that the composite is implemented but not yet validated.

## 0.1.0 (unreleased)

Initial public release.

### Core
- Voice packs: `data/<voice>/training-data` in, fully-derived `params/` out;
  self-protecting `.gitignore` dropped in every pack (created or healed by `learn`)
- `learn`: corpus indexing (register / polish / domain), per-register style
  profiles + exemplar banks, stylometric baselines with self-calibration,
  editable `style.yaml` + `rubrics.yaml` templates
- `plan`: deterministic pass-0 document eval — doc kind, content blend,
  math/dialogue/citation/URL densities, chunking seams, per-segment treatment
  and cautions; zero LLM, drop-in
- `run`: three-pass md/txt rewrite — register attribution (minimal-touch:
  on-target spans pass byte-identical), rewriting with rolling read-only context
  and per-span cautions, numeric/entity/length validation, AI-tell lint with
  retry, style.yaml (rules / phrase equivalences / qualitative lexicon /
  deterministic hard swaps), optional `--cohesion` seam-editing pass, span-level
  diff with before/after heterogeneity; `--raw`, `--json`, `--critique`
- `stats`: descriptive fingerprint, content-blend detection
  (concatenated-dump detector), voice-match scoring (Burrows' Delta, char/word
  n-grams, rhythm, vocab, punctuation) calibrated against corpus self-scores;
  text / json / md / html reports
- `judge` + `revoice/rubric/`: generic anchored categorical judging — the model
  classifies, the code computes; distribution-aware agreement descriptors
  (winner share/gap, n_eff, k-normalized decisiveness); own README + examples
- `serve --gui`: FastAPI server with full CLI↔API parity (voices lifecycle,
  revoice sync/async jobs, stats, plan, judge, review) + single-file bitwrench
  review GUI; span accept/reject/edit writes training pairs (the fine-tuning
  flywheel)
- `doctor`: config + provider round-trip diagnostics, plus privacy checks
  (pack .gitignore present, pack invisible to any surrounding git repo)
- `train prep`: fine-tuning dataset builder — reviewed flywheel pairs
  (accept/edit) + de-voicing bootstrap ((generic → authentic) pairs from
  polished corpus windows) → deduped chat-format train/valid JSONL, plus
  generated per-backend tooling: `run_mlx.sh` (Apple Silicon, mlx_lm.lora),
  `train_unsloth.py` (CUDA), and a README covering serving the adapter
  (mlx_lm.server → openai_compat provider), GGUF archival export, and
  pre-adoption evaluation via `stats`/`judge`

### Providers
- ollama, anthropic, openrouter, openai_compat (llama.cpp / LM Studio / mlx_lm /
  vLLM / LiteLLM-proxy), stub (offline testing); thinking-trace suppression
  throughout; each isolated in a single small file

### Quality & safety
- 100% test coverage (120 tests, offline, no LLM required), zero-warning ruff lint
- CI privacy/secrets gate: refuses tracked user data, env/credential files, and
  secret-shaped values (value patterns, not env-var names; `gate: allow-secret`
  escape for deliberate fakes)

### Examples & site
- Example voice packs: Mark Twain (20 docs), Charles Darwin (22 docs) — public
  domain, Project Gutenberg, two registers each
- GitHub Pages site + in-browser voice-match demo (client-side stylometrics
  against exported baselines, self-score normalized)
