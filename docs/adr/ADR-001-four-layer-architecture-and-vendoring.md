# ADR-001: Four-Layer Architecture and Vendored Core

- **Status:** Accepted
- **Date:** 2026-11-22
- **Invariants:** [INV-01](../INVARIANTS.md#inv-01-no-upstream-scion-fork-and-self-contained-kits)

## Context

Google Cloud Field Delivery Engineers build multiple agentic platforms for enterprise customers.
Platforms such as Gemini Enterprise CX (`gecx`) and Agent Development Kit (`adk`) share governance, security, and observability needs.
Forking upstream Scion creates merge debt on every upstream release.
Direct symlinks between packs and shared directories break inside Docker builds and offline customer handoffs.

## Decision

1. Structure the repository in four decoupled layers:
   - **Layer 0 (`vendor/`):** Read-only SHA-40 pinned upstream agent teams (`vendor/agent-team/`, `vendor/agents-cli/`).
   - **Layer 1 (`core-gcp-fde/`):** Domain-agnostic FDE skills, Vertex AI harness configs, Kaizen collector, and brownfield onboarding tools.
   - **Layer 2 (`packs/`):** Self-contained domain packs (`packs/gecx/`, `packs/adk/`, `packs/_template-pack/`).
   - **Layer 3 (`.factory/`):** Per-customer repository overlays emitted by `core-gcp-fde/scripts/factory_onboard.py`.
2. Consume upstream `GoogleCloudPlatform/scion` strictly as a pinned external binary, Helm chart, and container image dependency.
3. Vendor required `vendor/` and `core-gcp-fde/` files into each Release Kit at build time via `scripts/lib/release_kit.py` (`./build.sh --release-kit`).
4. Keep each pack isolated by its `pack_prefix` namespace so one Scion Hub can host multiple packs simultaneously.

## Consequences

- Teams add new target domains by creating a folder under `packs/` without changing `core-gcp-fde/` or Stage 01 networking.
- Every Release Kit runs inside air-gapped or private customer networks without cloning this catalog repository.
- Upstream Scion upgrades require only a version bump in `compat.yaml` and a regression pass.

## Enforcement

- `build.sh`
- `scripts/build.py`
- `scripts/lib/release_kit.py`
- `scripts/lib/lock_verifier.py`
- `tests/test_release_kit_build.py`
