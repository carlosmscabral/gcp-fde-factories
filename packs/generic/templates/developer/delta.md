# Developer Pack Delta (`packs/generic`)

1. Read `.factory/factory-profile.yaml`, `.factory/knowledge/invariants.md`, and `skills/<slug>-repo-conventions/SKILL.md` before editing code.
2. Respect `monorepo.subdir` when `monorepo.enabled` is true and follow the repository's existing language idioms, lint rules, and Git Flow conventions.
3. Keep entrypoints thin (`<= 200` lines) and split cohesive modules before exceeding `300` lines, documenting architecture rationale concisely.
4. Add or extend `.factory/Dockerfile.customer` only when the repository requires new container binaries, and validate changes with `factory_onboard.py validate-dockerfile`.
5. Run `python3 /opt/generic-factory/generic_sandbox_gate.py --level 1` and confirm exit `0` before opening a pull request or requesting review.
6. Never push directly to the base branch, never self-approve PRs, and never call cloud deployment APIs directly (leave Sandbox deploys to `sw-generic-deployer`).
