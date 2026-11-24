# ADR-012: Functional-First Live Hillclimbing Qualification

- **Status:** Accepted
- **Date:** 2026-11-24
- **Invariants:** [INV-16](../INVARIANTS.md#inv-16-functional-e2e-qualification-and-clean-teardown)

## Context

Unit tests and `terraform validate` verify syntax and local contracts, not real Google Cloud APIs, Org Policies, Helm admission rules, or live agent execution.
Optimizing latency or token cost before proving that end-to-end provisioning, bootstrapping, autonomous authoring, publishing, and teardown work in real GCP projects hides critical operational bugs.

## Decision

1. Adopt a two-wave Hillclimbing program defined in [HILLCLIMBING_CHARTER.md](../HILLCLIMBING_CHARTER.md).
2. Prioritize **Wave 1 (Functional and Operational Qualification)** across two real runtime topologies in parallel ephemeral GCP projects:
   - **Track A:** Lite Single-VM Factory operating `packs/gecx` to create, push, evaluate, verify, and clean up a real CES agent.
   - **Track B:** GKE Factory operating `packs/adk` to create, build, publish, evaluate, verify, and clean up a real Dockerfile-first ADK agent.
3. Defer Wave 2 latency, token-cost, and throughput optimizations until every Level 0 through Level 5 functional gate reaches 100% pass rate.
4. Feed every real operational defect discovered in live runs back into `gcp-fde-factories` with regression tests and updated ADRs.
5. Require verified 100% teardown of all ephemeral cloud projects and test repositories after every qualification run.

## Consequences

- Every release tag proves real end-to-end operability on Google Cloud rather than relying on mocks alone.
- Infrastructure drifts such as stale upstream module paths, missing API enablements, or image permissions surface before customer delivery.
- Ephemeral qualification runs leave zero ongoing cloud cost after completion.

## Enforcement

- [HILLCLIMBING_CHARTER.md](../HILLCLIMBING_CHARTER.md)
- `deploy/01-landing-zone/`, `deploy/02-factory-runtime/`, `deploy/03-hub-bootstrap/`
- `tests/`
