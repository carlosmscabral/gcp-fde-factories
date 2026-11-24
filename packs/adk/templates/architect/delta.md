# Architect Pack Delta (`packs/adk`)

1. Follow `google-agents-cli-scaffold` and `google-agents-cli-adk-code` to structure modular `app/` ADK packages (`app/fast_api_app.py`, `agents-cli-manifest.yaml`, `pyproject.toml`) without duplicating `deployment/terraform/`.
2. Choose between `export_mode: "agent_engine"` (`agents-cli deploy --deployment-target agent_runtime`) and `export_mode: "a2a"` (`cloud_run` or `gke`) explicitly in design specs.
3. Require a root `Dockerfile` so the same container runs cleanly across Agent Runtime, Cloud Run, and GKE.
4. Define explicit `tool_authorizations` (for `agent_engine`) or `agent_authorization` (for `a2a`) when agents access protected APIs.
5. Decouple inference region (`GOOGLE_CLOUD_LOCATION=global`) from Agent Runtime hosting region in every design.
6. Keep `evals/synthetic/` free of PII and require deterministic tool-trajectory assertions for every critical workflow.
