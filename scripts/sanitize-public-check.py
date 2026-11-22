#!/usr/bin/env python3
"""Thin CLI wrapper invoking scripts.lib.sanitizer for the public clean-room CI gate."""
from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.sanitizer import scan_repository


def main() -> int:
    """Scans the repository for internal leaks, PII patterns, and missing skill citations."""
    findings = scan_repository(REPO_ROOT)
    if findings:
        for item in findings:
            print(f"SANITIZE FAIL: {item}", file=sys.stderr)
        return 1
    print("SANITIZE PASS: 0 public clean-room violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
