# ADR-011: Public Clean-Room Gate and Runtime Denylist

- **Status:** Accepted
- **Date:** 2026-11-22
- **Invariants:** [INV-15](../INVARIANTS.md#inv-15-public-clean-room-sanitization-and-secret-denylist)

## Context

`gcp-fde-factories` is an open, public catalog shared with Google Cloud Field Delivery Engineers and enterprise customers.
Accidental commits of internal corporate links, sandbox project identifiers, billing IDs, customer names, or API tokens create immediate security and confidentiality incidents.

## Decision

1. Run `scripts/sanitize-public-check.py` (backed by `scripts/lib/sanitizer.py`) as a mandatory check inside `./build.sh --check` and `.github/workflows/ci.yml`.
2. Block all internal corporate URLs, corporate email domains, billing account patterns, sandbox project identifiers, and hardcoded secret patterns across all tracked files.
3. Enforce runtime secret isolation in Scion templates and skills: never echo environment credentials into logs, verdicts, or pull request comments.
4. Keep all live qualification tfvars, kubeconfigs, tokens, and experiment logs outside the repository in local scratch directories.

## Consequences

- Contributors receive immediate local feedback if a personal project ID or internal link enters any tracked file.
- Customer engagements can fork or mirror `gcp-fde-factories` directly without scrubbing private artifacts.

## Enforcement

- `scripts/sanitize-public-check.py`
- `scripts/lib/sanitizer.py`
- `build.sh`
- `tests/test_sanitizer.py`
