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

__version__ = "0.1.10"


def version() -> str:
    """revoice's version, matching `rubric.version()` and `voicemetric.version()`."""
    return __version__
