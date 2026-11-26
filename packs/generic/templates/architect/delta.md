# Architect Pack Delta (`packs/generic`)

1. Read `.factory/knowledge-index.yaml`, `.factory/knowledge/requirements.md`, `.factory/knowledge/invariants.md`, and `.factory/knowledge/decisions/README.md` before proposing any design.
2. Keep pre-existing repository structure, build systems, and AI instruction files intact without forcing greenfield rewrites on brownfield codebases.
3. When a change affects interfaces, data contracts, or cloud boundaries, draft a concise ADR under `.factory/knowledge/decisions/` and verify links with `factory_onboard.py kp-check --repo .`.
4. Explicitly list what Sandbox checks can prove versus `not_verifiable_in_sandbox` boundaries in every design brief.
5. Keep module boundaries small and acyclic (`<= 300` lines per module and thin entrypoints `<= 200` lines).
