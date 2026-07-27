#!/usr/bin/env python3
"""Data guard: reject any spreadsheet outside the whitelisted public sample.

The confidential dataset must never enter the repository — not in commits,
history, tests, fixtures, issues or documentation. This script is wired in
three places:

  * pre-commit hook  — receives staged filenames as arguments
  * CI               — run with --all to sweep every tracked file
  * manual           — either mode

Exit code 1 means a forbidden spreadsheet is present.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm", ".xlsb", ".xls", ".ods"}
WHITELIST = {Path("tests/fixtures/sample_public.xlsx")}


def is_forbidden(path: str) -> bool:
    p = Path(path)
    return p.suffix.lower() in SPREADSHEET_SUFFIXES and p not in WHITELIST


def tracked_and_staged_files() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return sorted(set(tracked) | set(staged))


def main(argv: list[str]) -> int:
    if "--all" in argv:
        candidates = tracked_and_staged_files()
    else:
        candidates = [a for a in argv if not a.startswith("-")]
        if not candidates:
            candidates = tracked_and_staged_files()

    offenders = [f for f in candidates if is_forbidden(f)]
    if offenders:
        print("BLOCKED: spreadsheets are not allowed in this repository.")
        print("The only permitted spreadsheet is tests/fixtures/sample_public.xlsx.")
        for f in offenders:
            print(f"  forbidden: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
