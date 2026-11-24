# ADR-009: Dockerfile-First ADK and Dual Gemini Enterprise Export

- **Status:** Accepted
- **Date:** 2026-11-24
- **Invariants:** [INV-13](../INVARIANTS.md#inv-13-dockerfile-first-adk-packaging-and-dual-ge-export)

## Context

Python pickle serialization (`cloudpickle`) creates brittle runtime dependencies, breaks across Python minor versions, and fails enterprise security reviews.
Enterprise customers using Google Agent Development Kit (ADK) need portable container artifacts that deploy cleanly to Vertex AI Agent Engine or Cloud Run.
Customers also vary in how they register agents inside Gemini Enterprise: some prefer UI ZIP uploads while others automate via Discovery Engine REST APIs.

## Decision

1. Standardize `packs/adk` on Dockerfile-first container packaging (`packs/adk/repo-scaffold/Dockerfile` with pinned `packs/adk/repo-scaffold/requirements.txt`, running as non-root UID 1000).
2. Avoid `cloudpickle` serialization by default across `packs/adk` templates, skills, scaffolds, and documentation.
3. Require modular ADK agent structure (`packs/adk/repo-scaffold/agent/agent.py` composition root plus `packs/adk/repo-scaffold/agent/config.py`, `packs/adk/repo-scaffold/agent/prompts.py`, and `packs/adk/repo-scaffold/agent/tools.py`).
4. Provide `packs/adk/scripts/ge_export.py` (backed by `packs/adk/scripts/lib/ge_payload.py` and validated by `schemas/ge-export.schema.json`) to generate dual Gemini Enterprise handoff outputs from `ge_manifest.json`:
   - `ge-console-bundle.zip` for UI console registration.
   - `register_agent.sh` calling the Discovery Engine `v1alpha` API with idempotent upsert semantics.
5. Keep `packs/adk/scripts/adk_sandbox_gate.py` and `scripts/verify-verdict.py` aligned to Contract 5 so ADK PRs produce auditable Verdicts tied to Vertex AI Agent Engine and Gemini Enterprise resources.

## Consequences

- ADK agents build deterministically via Cloud Build without local pickle compatibility issues.
- The same container image passes local `adk eval`, Cloud Run smoke tests, and Vertex AI Agent Engine deployment.
- Security teams can audit and sign container digests before promoting agents to Gemini Enterprise.

## Enforcement

- `packs/adk/repo-scaffold/Dockerfile`
- `packs/adk/scripts/ge_export.py`
- `packs/adk/scripts/adk_sandbox_gate.py`
- `schemas/ge-export.schema.json`
- `canaries/adk/check_ge_contract.py`
- `tests/test_adk_pack_and_ge_export.py`
