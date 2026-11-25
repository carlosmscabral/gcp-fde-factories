# ADR-015: Cognitive Brownfield Adaptation and Advisory Day-0 Contract Validators

- **Status:** Accepted (amends [ADR-008](ADR-008-adopt-first-brownfield-onboarding.md))
- **Date:** 2026-11-24
- **Linked Invariants:** [INV-12](../INVARIANTS.md#inv-12-non-destructive-brownfield-onboarding-and-config-schema)
- **Triggered By:** Live Hillclimbing Round 5 (`HC-2026-11-24-05`, findings `HC05-F3`, `HC05-F4`, `HC05-F5`) and enterprise monorepo onboarding analysis

## Context

Enterprise brownfield repositories contain arbitrary build systems, monorepo CLIs (such as `nx`), custom CI workflows, pre-existing AI instruction files, and workspace hooks.
A static 12-binary allowlist (`INSTALL_RECIPES`) cannot predict every customer toolchain or workflow structure.
During live `HC-05` qualification, three onboarding gaps emerged:

1. `scripts/lib/onboard_scanner.py` did not report untrusted workspace hooks (`.claude/settings.json`, `.githooks/`) or diverging AI files (`AGENTS.md` versus `CLAUDE.md`).
2. `scripts/lib/onboard_emitter.py` did not append `.scion/agents/` to `.gitignore` on raw brownfield repositories, causing `scion start` to fail with a security error.
3. Day-0 factory setup needs fluid adoption without blocking teams over advisory security findings, while PR and runtime security auditing (`security-auditor`) stays strict.

## Decision

1. **Combine cognitive Day-0 authoring with deterministic integrity and advisory validators:**
   - The `factory-onboard` skill guides the onboarding agent to run 0-token `factory_onboard.py scan` first, then cognitively read manifests, CI pipelines, AI files, and hooks.
   - The onboarding agent synthesizes concrete `absorbed_conventions` into `skills/<slug>-repo-conventions/SKILL.md`, adapts existing CI workflows non-destructively, and may author a tailored `.factory/Dockerfile.customer` for arbitrary customer binaries (such as `nx` or custom CLIs) beyond the optional presets in `INSTALL_RECIPES`.
2. **Add deterministic Day-0 Dockerfile and coexistence validation with advisory-default mode:**
   - `scripts/lib/onboard_scanner.py` detects untrusted workspace hooks (`.claude/settings*.json`, `.gemini/settings*.json`, `.githooks/`, `.husky/`) and diverging AI instruction files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`), emitting clear `advisory_findings` and `modernization_gaps` (`GAP-UNTRUSTED-HOOKS`, `GAP-AI-DIVERGENCE`) without blocking setup.
   - `core-gcp-fde/scripts/factory_onboard.py validate-dockerfile` (backed by `scripts/lib/dockerfile_recipes.py`) validates any agent-authored `.factory/Dockerfile.customer` for digest-pinned `@sha256:` `FROM`, non-root `USER scion`, shell-pipe installs (`curl|sh`, `wget|bash`), and a post-`USER` smoke check.
   - By default, security findings emit named warnings and exit `0` so Day-0 onboarding stays fluid. Passing `--strict` turns security findings into exit `1` failures for teams that require blocking setup checks.
   - Structural corruption and anti-clobber checks (invalid YAML/JSON, malformed `AGENTS.md` markers, symlink writes, missing `FROM`) always fail closed.
3. **Preserve `.gitignore` runtime safety and keep `security-auditor` strict:**
   - `scripts/lib/onboard_emitter.py` idempotently appends `.scion/agents/` to `.gitignore` (preserving existing entries and CRLF/LF endings) and preserves an already agent-authored `.factory/Dockerfile.customer` when `missing_binaries` is empty.
   - `packs/adk/templates/security-auditor/delta.md` and `packs/gecx/templates/security-auditor/delta.md` remain strict and unchanged for PR and runtime auditing.

## Consequences

- Teams with arbitrary monorepo toolchains (such as `nx` or custom internal CLIs) onboard in one Day-0 session without waiting for upstream allowlist changes.
- Day-0 setup surfaces untrusted hooks, AI divergence, and Dockerfile hygiene clearly in onboarding output and `.factory/modernization-backlog.yaml` without stalling initial factory bringup.
- Strict PR security auditing (`security-auditor`), anti-clobber guarantees, and runtime IAM boundaries remain intact.

## Enforcement

- `core-gcp-fde/skills/factory-onboard/SKILL.md`
- `core-gcp-fde/scripts/factory_onboard.py` (`validate-dockerfile`)
- `scripts/lib/onboard_scanner.py`, `scripts/lib/onboard_parsers.py`, `scripts/lib/onboard_emitter.py`, and `scripts/lib/dockerfile_recipes.py`
- `schemas/factory-profile.schema.json`
- `tests/test_hc05_brownfield_and_adr015.py`
