# ADR-014: Native `google-agents-cli` (`adk_python`) Layout for `packs/adk`

- **Status:** Accepted (amends [ADR-009](ADR-009-dockerfile-first-adk-and-dual-ge-export.md))
- **Date:** 2026-11-24
- **Linked Invariants:** [INV-13](../INVARIANTS.md#inv-13-dockerfile-first-adk-packaging-and-dual-ge-export), [INV-12](../INVARIANTS.md#inv-12-non-destructive-brownfield-onboarding-and-config-schema)
- **Triggered By:** Live Hillclimbing Round 3 (`HC-03 F4`) and Round 4 A2A card audit

## Context

`packs/adk` embeds seven upstream `google-agents-cli` (`v1.15.0`) skills (`workflow`, `scaffold`, `adk-code`, `eval`, `deploy`, `publish`, `observability`).
Those upstream skills assume every Python ADK project uses the `adk_python` scaffold layout (`app/agent.py`, `app/fast_api_app.py`, `agents-cli-manifest.yaml`, `pyproject.toml`, and `uvicorn app.fast_api_app:app`).

The initial `packs/adk/repo-scaffold/` used a minimal custom layout (`agent/` plus `adk api_server --a2a /app` plus static `agent/agent.json`).
During live `HC-03` and `HC-04` qualification, that divergence caused three concrete issues:

1. **Skill-to-scaffold mismatch:** Upstream `google-agents-cli-*` skills never mention static `agent/agent.json` because `app/fast_api_app.py` registers A2A routes dynamically in Python.
2. **Static A2A URL drift:** `adk api_server --a2a` echoes the static `url` stored inside `agent/agent.json` (`http://localhost:8080/a2a/agent`) instead of deriving the service URL from runtime configuration (`APP_URL`).
3. **Missing Reasoning Engine routes:** Running bare `adk api_server` omits `/api/reasoning_engine` and `/api/stream_reasoning_engine` routes needed by the Vertex AI Agent Engine Playground and native `:streamQuery` calls.

## Decision

1. **Adopt the native `google-agents-cli` (`adk_python`) scaffold layout in `packs/adk/repo-scaffold/`:**
   - Replace `agent/` and `requirements.txt` with `app/`, `agents-cli-manifest.yaml`, and `pyproject.toml`.
   - Keep `app/agent.py` as a thin composition root (`<= 250` lines) that lazily exports `root_agent` and `app = App(root_agent=root_agent, name="app")`, while keeping `app/config.py`, `app/prompts.py`, and `app/tools.py` in dedicated submodules.
   - Ship `app/fast_api_app.py` and `app/app_utils/{a2a.py,services.py,reasoning_engine_adapter.py}` so one container serves ADK HTTP (`/apps/app/...`, `/run_sse`), dynamic A2A (`/a2a/app/.well-known/agent-card.json` and `/a2a/app` with v0.3 JSON-RPC compatibility), and Agent Engine Playground routes (`/api/reasoning_engine` and `/api/stream_reasoning_engine`).
2. **Harden the root `Dockerfile` without breaking `agents-cli` compatibility:**
   - Use `uv` with `pyproject.toml` (and optional `uv.lock`) inside `packs/adk/repo-scaffold/Dockerfile`.
   - Run `uvicorn app.fast_api_app:app --host 0.0.0.0 --port ${PORT:-8080}` under non-root `USER appuser` (UID 1000) so Cloud Run, GKE, and Agent Runtime share one non-root container contract.
3. **Omit duplicate `deployment/terraform/` from the scaffold:**
   - Stage 01 (`deploy/01-landing-zone/`) owns customer VPCs, zero-PII Custom Roles, split Service Accounts, GitHub WIF, and FinOps budgets.
   - `packs/adk/repo-scaffold/` omits `agents-cli`'s generated `deployment/terraform/` directory to avoid conflicting IAM or networking definitions.
4. **Preserve the thin Factory Governance overlay and brownfield adoption:**
   - Retain `.factory/hub-project.yaml`, `.github/workflows/adk-verdict-gate.yml`, `evals/`, `ge_manifest.json`, `knowledge-plane/INDEX.md`, and byte-identical `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md`.
   - Update `packs/adk/scripts/adk_sandbox_gate.py` to auto-detect `app/` first and fall back to `agent/` so brownfield ADK repositories adopted via `factory-onboard` keep working without forced rewrites.
   - Update `scripts/lib/onboard_parsers.py` to detect `agents-cli-manifest.yaml` alongside `ge_manifest.json`.

## Consequences

- All seven vendored `google-agents-cli-*` skills match the `packs/adk/repo-scaffold/` file tree, commands, and HTTP routes directly.
- A2A `AgentCard` endpoints (`/a2a/app/.well-known/agent-card.json`) generate dynamically from `root_agent` and `APP_URL`, removing static `agent/agent.json` maintenance.
- One container image serves ADK HTTP, A2A v0.3/v1.0 JSON-RPC, and Vertex AI Agent Engine Playground endpoints across Cloud Run, GKE, and Agent Runtime.
- Existing brownfield repositories using `agent/` or custom layouts continue working through `factory-onboard` (INV-12).

## Enforcement

- `packs/adk/repo-scaffold/agents-cli-manifest.yaml`
- `packs/adk/repo-scaffold/pyproject.toml`
- `packs/adk/repo-scaffold/Dockerfile`
- `packs/adk/repo-scaffold/app/` (`agent.py`, `config.py`, `prompts.py`, `tools.py`, `fast_api_app.py`, `app_utils/`)
- `packs/adk/scripts/adk_sandbox_gate.py`
- `scripts/lib/onboard_parsers.py`
- `tests/test_adk_pack_and_ge_export.py` and `tests/test_hc03_factory_ops.py`
