# Starter ADK Agent (`packs/adk` — Native `google-agents-cli` Layout)

Modular Google Cloud Agent Development Kit (ADK) repository following the native `google-agents-cli` (`adk_python`) contract (ADR-014) with the `gcp-fde-factories` governance overlay.

## Layout

- `app/agent.py` — Thin composition root exporting `root_agent` and `app = App(root_agent=root_agent, name="app")`.
- `app/config.py`, `app/prompts.py`, `app/tools.py` — Isolated configuration, prompts, and deterministic tools.
- `app/fast_api_app.py` & `app/app_utils/` — Unified FastAPI entrypoint serving ADK HTTP (`/apps/app/...`, `/run_sse`), dynamic A2A (`/a2a/app/.well-known/agent-card.json` and `/a2a/app`), and Agent Engine Playground routes (`/api/reasoning_engine`, `/api/stream_reasoning_engine`).
- `agents-cli-manifest.yaml` & `pyproject.toml` — Native `google-agents-cli` metadata and pinned dependencies.
- `Dockerfile` — Non-root (`USER appuser`) container running `uvicorn app.fast_api_app:app`.
- `.factory/`, `.github/workflows/adk-verdict-gate.yml`, `evals/`, `ge_manifest.json` — Factory governance, anti-forgery Verdict Gate, and Gemini Enterprise export contract.

## Local Verification

```bash
pytest tests/ -q
python3 /opt/adk-factory/ge_export.py validate --manifest ge_manifest.json
```
