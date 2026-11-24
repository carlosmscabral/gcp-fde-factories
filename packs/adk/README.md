# `packs/adk` (Pilot Pack 2 — ADK + Gemini Enterprise App Export)

Reusable autonomous software factory pack for **Google Cloud Agent Development Kit (ADK)** agents running on **Vertex AI Agent Engine** or **A2A** runtimes, with built-in deterministic export and registration into **Gemini Enterprise (`GE App`)**.

## Capabilities

- **16 Offline Prefix-Scoped Templates (`adk-*`):** Preston's complete 13-role `agent-team` hierarchy + split-SA Sandbox roles (`adk-deployer`, `adk-eval-tester`) + closed-loop Kaizen (`adk-kaizen-analyst`).
- **Dual Gemini Enterprise (`GE App`) Export:**
  - `export_mode: "agent_engine"` emits Discovery Engine `v1alpha` `adkAgentDefinition.provisionedReasoningEngine` payloads.
  - `export_mode: "a2a"` emits canonical A2A `AgentCard` JSON wrapped in `a2aAgentDefinition.jsonAgentCard`.
- **Anti-Forgery Verification:** Offline Level 1 (`pytest`, CloudPickle round-trip check, `ge_export.py validate`) + Level 2 Sandbox (`adk eval` + ephemeral `[CI]` GE registration + Janitor cleanup) + `.github/workflows/adk-verdict-gate.yml`.
- **Brownfield Ready:** Ships `packs/adk/toolchain-manifest.json` for `factory_onboard.py` (`v0.4.0`) conditional `Dockerfile.customer` generation.
