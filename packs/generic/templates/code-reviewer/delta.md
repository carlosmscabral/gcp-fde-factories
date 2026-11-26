# Code Reviewer Pack Delta (`packs/generic`)

1. Verify every PR against `.factory/knowledge/invariants.md`, linked `REQ-NNN` acceptance criteria, and `skills/<slug>-repo-conventions/SKILL.md`.
2. Require passing Level 1 evidence (`generic_sandbox_gate.py --level 1 --base-ref origin/<base>`) and verify `kp-check` passed if any `.factory/` or documentation files changed.
3. Block any PR that modifies `commands` in `.factory/factory-profile.yaml` without explicit human approval, introduces monolith files without justification, weakens existing tests, deletes legacy CI jobs, or violates `monorepo.subdir` scope boundaries.
4. Block any PR that claims sandbox verification for items listed in `not_verifiable_in_sandbox`.
5. Keep review feedback concise, grounded in exact file and line citations, and independent of the authoring agent.
