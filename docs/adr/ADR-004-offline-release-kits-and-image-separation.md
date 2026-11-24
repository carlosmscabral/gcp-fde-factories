# ADR-004: Offline Release Kits and Image Separation

- **Status:** Accepted
- **Date:** 2026-11-23
- **Invariants:** [INV-05](../INVARIANTS.md#inv-05-offline-release-kit-integrity-and-sha256-checksums), [INV-06](../INVARIANTS.md#inv-06-digest-pinned-runtime-and-harness-images)

## Context

Enterprise environments often block direct pulls from external registries or GitHub repositories during delivery.
Mixing lean CI verification containers with full Scion agent harness containers caused runtime failures.
Scion agent pods require `sciontool`, `tmux`, and harness CLIs (`antigravity` or `claude`) baked into their container image.
CI verification jobs only need Python, `uv`, `cxas`, or `adk` without harness binaries.

## Decision

1. Package each pack into an offline Release Kit via `scripts/lib/release_kit.py` (`./build.sh --release-kit`) containing `manifest.json`, `SHA256SUMS`, templates, skills, harness configs, `repo-scaffold/`, `core-gcp-fde/images/base.Dockerfile`, and `packs/<pack>/Dockerfile`.
2. Separate container images into two classes:
   - **Lean CI runtime image (`<pack>-runtime`):** Built from `python:3.12-slim-bookworm` for GitHub Actions and local gates.
   - **Scion agent harness images (`<pack>-antigravity-runtime`, `<pack>-claude-runtime`):** Built by layering `core-gcp-fde/images/base.Dockerfile` and `packs/<pack>/Dockerfile` onto pinned upstream Scion harness base images (`ghcr.io/homebrew-scion/scion-antigravity:<version>` or `scion-claude:<version>`).
3. Make `--mode rebuild` the default in `deploy/03-hub-bootstrap/stage-release-kit.sh` using Cloud Build (`deploy/03-hub-bootstrap/cloudbuild.yaml`) inside the customer Hub project.
4. Require immutable `@sha256:` image digests in `manifest.json` and `harness-configs/*/config.yaml` before `deploy/03-hub-bootstrap/bootstrap-hub-project.sh` succeeds.
5. Support `--mode mirror` (`crane` or `gcrane`) only when source images already carry valid non-placeholder `@sha256:` digests.

## Consequences

- Operators ship one self-contained directory with verifiable `SHA256SUMS` into restricted customer environments.
- CI runners stay small and fast while Scion agent containers boot with working `sciontool` hooks.
- Tag mutation attacks cannot alter running factory containers because every reference pins an immutable SHA-256 digest.

## Enforcement

- `scripts/lib/release_kit.py`
- `deploy/03-hub-bootstrap/stage-release-kit.sh`
- `deploy/03-hub-bootstrap/cloudbuild.yaml`
- `deploy/03-hub-bootstrap/bootstrap-hub-project.sh`
- `tests/test_release_kit_build.py`
