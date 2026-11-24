---
name: adk-ge-export-contract
description: Deterministic export and registration contract for exposing ADK agents to Gemini Enterprise (GE App) via adkAgentDefinition (Vertex AI Agent Engine) or a2aAgentDefinition (A2A AgentCard).
---

# ADK to Gemini Enterprise (`GE App`) Export Contract

## 1. Choose Between `agent_engine` and `a2a` Export Modes
- Maintain one declarative `ge_manifest.json` at the target repository root validated against `schemas/ge-export.schema.json`.
- Use `export_mode: "agent_engine"` when the ADK agent deploys to Vertex AI Agent Engine (`reasoningEngines/{id}`). This generates an `adkAgentDefinition.provisionedReasoningEngine` payload.
- Use `export_mode: "a2a"` when exposing the agent via Agent2Agent (`to_a2a(root_agent)` or `adk api_server --a2a` on Cloud Run, GKE, or Agent Engine). This generates a canonical `AgentCard` and encodes it into `a2aAgentDefinition.jsonAgentCard`.
- source: https://cloud.google.com/gemini/enterprise/docs/register-and-manage-an-adk-agent

## 2. Gemini Enterprise Discovery Engine API Contract
- Target the official Discovery Engine agents collection endpoint:
  `https://{endpoint_prefix}discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/{location}/collections/default_collection/engines/{app_id}/assistants/{assistant_id}/agents`
  where `endpoint_prefix` is empty for `global` and `{endpoint_location}-` for `us` or `eu`.
- Always validate and materialize the deterministic export bundle (`ge_registration_payload.json`, optional `agent_card.json`, and `ge_export_manifest.json` with SHA-256 digests) using `python3 /opt/adk-factory/ge_export.py export --manifest ge_manifest.json --out dist/ge-export`.
- Include explicit `authorizationConfig.toolAuthorizations` only when the agent requires configured OAuth authorization resources in Gemini Enterprise.
- source: https://cloud.google.com/gemini/enterprise/docs/register-and-manage-an-a2a-agent

## 3. Environment Boundary and Ephemeral Cleanup
- Factory agents (`adk-deployer`) may register ephemeral `[CI]` agents ONLY inside the designated Sandbox Gemini Enterprise App, and MUST delete them on failure or after CI verification via `ge_export.py delete`.
- Production, Staging, and DEV Gemini Enterprise App registrations occur exclusively inside customer CI/CD (Workload Identity Federation) after explicit human pull request approval.
- source: canaries/adk/ge_export_contract.json
