#!/usr/bin/env python3
"""CI gate: fail if any user data, env files, or secrets are tracked by git.

Voice packs are personal data. Nothing under a pack (corpus, profiles, review
pairs) or a local config may ever be committed. This scans `git ls-files`
(tracked + staged) and fails loudly on violations.

Rules — a tracked path fails if it:
  1. is under a top-level data/ directory
  2. contains /params/            (derived voice data: profiles, pairs, baselines)
  3. contains training-data/      UNLESS under examples/voices/ (bundled demos)
  4. is named pairs.jsonl, calibration.json, baselines.json, or index.jsonl
     UNLESS under examples/ or tests/
  5. is revoice.yaml (local config; revoice.example.yaml is fine)
  6. looks like an env/credential file (.env*, *.pem, *.key, id_rsa*, credentials*)
  7. CONTAINS a secret-shaped value (API keys, tokens, private-key blocks) —
     value shapes only, never env-var NAMES (docs legitimately say ANTHROPIC_API_KEY).
     Deliberate fakes in tests/docs: put `gate: allow-secret` on the same line.

This is the narrow, self-owned net. The broad net is GitHub push protection —
enable it in repo settings (Settings -> Code security -> Push protection).

Run locally:  python scripts/check_no_user_data.py
CI runs it after checkout, before tests.
"""

from __future__ import annotations

import re
import subprocess
import sys

ALLOWED_PREFIXES = ("examples/voices/",)
SENSITIVE_NAMES = {"pairs.jsonl", "calibration.json", "baselines.json", "index.jsonl"}

ENV_FILE_RX = re.compile(
    r"(^|/)(\.env(\..+)?|.*\.pem|.*\.p12|.*\.pfx|id_rsa[^/]*|id_ed25519[^/]*|.*\.keystore|credentials([._-].*)?|\.netrc|\.npmrc|\.pypirc)$"
)

# value shapes, not names. Each: (regex, label)
SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "anthropic api key"),
    (re.compile(r"sk-or-v?1?-[A-Za-z0-9_-]{20,}"), "openrouter api key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{32,}"), "openai-style api key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "github token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"), "github fine-grained token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws access key id"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "google api key"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "slack token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "private key block"),
    (re.compile(r"\bpypi-AgEI[A-Za-z0-9_-]{20,}"), "pypi token"),
    (re.compile(r"_authToken\s*=\s*\S{16,}"), "npm auth token"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{40,}\.eyJ[A-Za-z0-9_-]{40,}\."), "jwt"),
    (re.compile(r"""(?i)\b(?:api_?key|secret|token|password)\b\s*[:=]\s*["'][A-Za-z0-9+/_-]{24,}["']"""),
     "hardcoded credential assignment"),
]

ALLOW_MARK = "gate: allow-secret"
SKIP_CONTENT_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2",
                     ".ttf", ".zip", ".gz", ".lock", ".gguf", ".bin"}
MAX_SCAN_BYTES = 1_000_000


def secret_violations(paths: list[str]) -> list[tuple[str, str]]:
    bad = []
    for p in paths:
        norm = p.replace("\\", "/")
        if ENV_FILE_RX.search(norm):
            bad.append((p, "env/credential file — must never be tracked"))
            continue
        ext = "." + norm.rsplit(".", 1)[-1] if "." in norm else ""
        if ext.lower() in SKIP_CONTENT_EXTS:
            continue
        try:
            with open(p, "rb") as f:
                raw = f.read(MAX_SCAN_BYTES)
            if b"\x00" in raw[:8000]:
                continue  # binary
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if ALLOW_MARK in line:
                continue
            for rx, label in SECRET_PATTERNS:
                if rx.search(line):
                    bad.append((f"{p}:{i}", f"looks like a {label}"))
                    break
    return bad


def violations(paths: list[str]) -> list[tuple[str, str]]:
    bad = []
    for p in paths:
        norm = p.replace("\\", "/")
        name = norm.rsplit("/", 1)[-1]
        if norm.startswith("data/") or "/data/" in norm and not norm.startswith(ALLOWED_PREFIXES):
            if norm.startswith("data/"):
                bad.append((p, "under data/ — voice packs must never be committed"))
                continue
        if "/params/" in norm or norm.startswith("params/"):
            bad.append((p, "contains /params/ — derived voice data"))
            continue
        if "training-data/" in norm and not norm.startswith(ALLOWED_PREFIXES):
            bad.append((p, "training-data outside examples/voices/"))
            continue
        if name in SENSITIVE_NAMES and not norm.startswith(("examples/", "tests/")):
            bad.append((p, f"{name} — voice-pack artifact"))
            continue
        if norm == "revoice.yaml":
            bad.append((p, "local config — commit revoice.example.yaml instead"))
    return bad


def main() -> int:
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"check_no_user_data: cannot list git files ({e}); skipping", file=sys.stderr)
        return 0
    paths = [line for line in out.stdout.splitlines() if line.strip()]
    bad = violations(paths) + secret_violations(paths)
    if bad:
        print("USER DATA / SECRETS FOUND IN GIT — refusing:", file=sys.stderr)
        for p, why in bad:
            print(f"  {p}\n      -> {why}", file=sys.stderr)
        print("\nRemove with: git rm --cached <path>  (file stays on disk)", file=sys.stderr)
        return 1
    print(f"check_no_user_data: OK ({len(paths)} tracked files clean)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
