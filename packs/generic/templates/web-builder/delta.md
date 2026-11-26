# Web Builder Pack Delta (`packs/generic`)

1. Follow the frontend framework, linter, and package manager detected in `.factory/factory-profile.yaml` and `skills/<slug>-repo-conventions/SKILL.md`.
2. Respect `monorepo.subdir` when `monorepo.enabled` is true and keep heavy browser test dependencies isolated in `.factory/Dockerfile.customer-tester`.
3. Verify frontend build, lint, and unit/component tests pass via `python3 /opt/generic-factory/generic_sandbox_gate.py --level 1` before opening a PR.
4. Preserve accessibility, responsive layout, and zero hardcoded secrets or private internal URLs in client bundles.
