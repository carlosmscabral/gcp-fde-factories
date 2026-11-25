# ADR-008: Adopt-First Brownfield Onboarding

- **Status:** Accepted (amended by [ADR-015](ADR-015-cognitive-brownfield-adaptation-and-contract-validators.md))
- **Date:** 2026-11-23
- **Invariants:** [INV-12](../INVARIANTS.md#inv-12-non-destructive-brownfield-onboarding-and-config-schema)

## Context

Most enterprise engagements start with an existing agent codebase or an existing live CES app rather than an empty repository.
Forcing teams to move source files into a rigid greenfield layout breaks existing CI pipelines and delays adoption.

## Decision

1. Provide a single deterministic onboarding CLI (`core-gcp-fde/scripts/factory_onboard.py` backed by `scripts/lib/onboard_scanner.py`, `scripts/lib/onboard_parsers.py`, and `scripts/lib/onboard_emitter.py`) supporting `scan`, `check`, and `emit` subcommands.
2. Inspect existing local Git repositories (and exported CES apps) without moving, renaming, or deleting existing customer files.
3. Capture customer repository topology, toolchain pins, and factory profile inside `.factory/factory-profile.yaml` and `.factory/hub-project.yaml`, validated against `schemas/factory-profile.schema.json` and `schemas/hub-project.schema.json`.
4. Emit a non-destructive `.factory/modernization-backlog.yaml`, `.factory/knowledge-index.yaml`, and bounded `AGENTS.md` block cataloging missing guardrails, tests, Dockerfiles, or evaluation suites.
5. Make `emit` strictly additive and idempotent, generating conditional `Dockerfile.customer` overlays only when extra customer dependencies exist (`scripts/lib/dockerfile_recipes.py`).

## Consequences

- Existing teams adopt factory guardrails, eval gates, and Kaizen telemetry in minutes with zero disruptive file renames.
- Gaps detected during onboarding become prioritized items for the factory's first coding waves.

## Enforcement

- `core-gcp-fde/scripts/factory_onboard.py`
- `scripts/lib/onboard_scanner.py`
- `scripts/lib/onboard_emitter.py`
- `schemas/factory-profile.schema.json`
- `schemas/hub-project.schema.json`
- `tests/test_brownfield_onboard_v040.py`
