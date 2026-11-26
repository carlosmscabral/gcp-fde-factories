---
name: adk-ge-export-contract
description: Deterministic Gemini Enterprise (GE App) export and registration contract supporting Vertex AI Agent Engine and A2A v0.3.0 modes.
---

# Gemini Enterprise (`GE App`) Export Contract

## 1. Dual Registration Modes (`Discovery Engine v1alpha`)
- Support two explicit `export_mode` targets in `ge_manifest.json`, validated against `schemas/ge-export.schema.json`:
  - **`agent_engine`:** emits `adkAgentDefinition.provisionedReasoningEngine.reasoningEngine` targeting a Vertex AI Agent Engine resource. Never emit undefined `toolSettings`.
  - **`a2a`:** emits a valid A2A `v0.3.0` `AgentCard` (including mandatory `tags` per skill) and wraps it in `a2aAgentDefinition.jsonAgentCard`.
- Use `https://{endpoint_prefix}discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{location}/collections/default_collection/engines/{app_id}/assistants/{assistant_id}/agents` where `endpoint_prefix` matches `location` (`""` for `global`, `"us-"` for `us`, `"eu-"` for `eu`).
- source: https://cloud.google.com/agentspace/docs/register-agents

## 2. Deterministic Bundle Export and OAuth Contracts
- Run `python3 /opt/adk-factory/ge_export.py export --manifest ge_manifest.json --out dist/ge-export` on every PR.
- Use `authorizationConfig.toolAuthorizations` for `agent_engine` tool OAuth and `authorizationConfig.agentAuthorization` for `a2a` invocation OAuth.
- Never embed client secrets, OAuth tokens, or real user PII in `ge_manifest.json` or exported bundles.
- source: https://google.github.io/adk-docs/a2a/

## 3. Sandbox Registration Quota, License Preflight, and Production Promotion Boundary
- Run `python3 /opt/adk-factory/ge_export.py preflight --manifest ge_manifest.json` before calling `register` or `patch`. If the Sandbox project has zero active `licenseConfigs` or disabled `default_user_store` auto-registration (exit code `2`), deliver `dist/ge-export/` cleanly without retrying `agents:create`.
- Prefer `ge_export.py patch --agent-name <sandbox-agent>` over per-PR `POST` creation to avoid Gemini Enterprise daily agent-creation `HTTP 429` quotas.
- Allow `adk-deployer` to register or patch `[CI]` agents strictly inside the disposable Sandbox project (`project_id == --sandbox-project`).
- Promote DEV, HML, and PRD Gemini Enterprise registrations exclusively via customer CI/CD with WIF (using a licensed principal or dedicated seated SA) after human PR approval.
- source: https://cloud.google.com/agentspace/docs/register-agents
