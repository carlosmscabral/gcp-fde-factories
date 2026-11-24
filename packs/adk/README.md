# `packs/adk` (Pilot Pack 2 — ADK 2.15 + Dockerfile-First + Gemini Enterprise App Export)

Reusable autonomous software factory pack for **Google Cloud Agent Development Kit (`google-adk[eval,a2a]==2.15.0`)** agents using an opinionated container-first root `Dockerfile` deployment contract, vendored upstream **`google/agents-cli v1.15.0`** skills, and deterministic export and registration into **Gemini Enterprise (`GE App`)**.

## Capabilities

- **16 Offline Prefix-Scoped Templates (`adk-*`):** Preston's complete 13-role `agent-team` hierarchy + split-SA Sandbox roles (`adk-deployer`, `adk-eval-tester`) + closed-loop Kaizen (`adk-kaizen-analyst`).
- **18 Hub Skill Bank Skills:** 5 project-attached guardrails/contracts + 6 SEP/Kaizen skills + all 7 role-scoped Apache-2.0 skills vendored from `google/agents-cli@2fa159a8` (`workflow`, `adk-code`, `scaffold`, `eval`, `deploy`, `publish`, `observability`) within the 1,800-line per-role context budget.
- **Opinionated Dockerfile-First Deployment (`packs/adk/repo-scaffold/Dockerfile`):** Ships a reproducible container entrypoint (`adk api_server`) aligned with `agents-cli deploy` across Vertex AI Agent Engine Runtime, Cloud Run, and GKE.
- **Dual Gemini Enterprise (`GE App`) Export (`packs/adk/scripts/ge_export.py`):**
  - `export_mode: "agent_engine"` emits Discovery Engine `v1alpha` `adkAgentDefinition.provisionedReasoningEngine` payloads (with optional `toolAuthorizations`, supporting `POST` and in-place `PATCH`).
  - `export_mode: "a2a"` emits canonical A2A `v0.3.0` `AgentCard` JSON (with required `AgentSkill.tags`) wrapped in `a2aAgentDefinition.jsonAgentCard` (with optional `agentAuthorization`).
- **Split-SA Anti-Forgery Verification & Dual Janitor:** Offline Level 1 (`pytest`, root `Dockerfile` contract check, `ge_export.py validate`) + Level 2 Sandbox (`adk eval` under predict-only `sandboxEvaluatorPredict` + ephemeral `[CI]` GE registration) + paginated dual Janitor sweeping both Vertex AI `reasoningEngines` (`?force=true`) and Discovery Engine `agents` + `.github/workflows/adk-verdict-gate.yml`.
- **Brownfield Ready & Vertex AI-First:** Ships `packs/adk/toolchain-manifest.json` and `packs/adk/compat.yaml` with Vertex AI generic model tiers (`small`, `medium`, `large`, `extra-large`) and default `weekly-kaizen` scheduling.
