"""revoice — rewrite documents in your own voice, structure preserved.

**This module is the single source of truth for revoice's version.** `pyproject.toml`
reads `__version__` from here via setuptools' dynamic-version support, so the packaged
metadata cannot disagree with the running code. Everything else that shows a version —
the website's `pages/version.js`, the docs, the release tag, the GitHub Release — is
generated or derived from this one assignment.

That matters more than tidiness. A version written in two places is a version that will
eventually be wrong in one of them, and the failure is silent: the package says one
thing, the site says another, and a bug report cites a build that never existed.

To release, bump this line and run `scripts/release.sh` — see CONTRIBUTING.md.

The two embedded engines version themselves independently and deliberately:
`revoice.rubric.version()` and `revoice.voicemetric.version()`.
"""

__version__ = "0.1.11"


# --- runtime version support ---------------------------------------------------
# Every package in this family reports its own version at runtime, in a form you can
# print and a form you can compare: bitwrench has `bw.version` / `bw.versionInfo` /
# `bw.getVersion()`, fr_math has FR_MATH_VERSION alongside a packed FR_MATH_VERSION_HEX.
# A string is for humans and logs; a tuple is for `if version_info() >= (0, 2)`, which
# string comparison gets wrong the moment a component reaches double digits ("0.1.10"
# sorts before "0.1.9").

__version_info__ = tuple(int(p) for p in __version__.split("."))


def version_info() -> tuple[int, ...]:
    """The version as integers, for comparison. `version()` is the one to print."""
    return __version_info__


def version() -> str:
    """revoice's version, matching `rubric.version()` and `voicemetric.version()`."""
    return __version__


def versions() -> dict:
    """Every component's version in one call — the thing a bug report should carry.

    revoice is three versioned pieces that move independently: the tool, the metric
    engine, and the rubric engine. Asking each one separately means a report that
    mentions the tool and omits the engine that produced the numbers, which is the half
    that decides whether two results are comparable at all. Hence `signature` here too:
    it changes when the scoring configuration changes, without the version moving.
    """
    from revoice import rubric
    from revoice import voicemetric as _vm

    return {
        "revoice": __version__,
        "voicemetric": _vm.version(),
        "voicemetric_signature": _vm.signature(),
        "rubric": rubric.version(),
    }
