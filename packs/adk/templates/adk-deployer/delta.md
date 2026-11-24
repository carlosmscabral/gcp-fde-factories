# ADK Deployer Pack Delta (`packs/adk`)

1. Operate strictly with `--service-account adk-deployer` inside the disposable Sandbox project only.
2. Follow `google-agents-cli-deploy` and `google-agents-cli-publish` using Dockerfile-first container deployment (`agents-cli deploy --deployment-target agent_runtime` or `cloud_run`) without passing reserved `GOOGLE_CLOUD_PROJECT` or `GOOGLE_CLOUD_QUOTA_PROJECT` vars in Agent Engine `deploymentSpec.env`.
3. Verify the root `Dockerfile` (`uvicorn app.fast_api_app:app`, non-root `USER`), `agents-cli-manifest.yaml`, and pinned `pyproject.toml` before every Sandbox deployment, passing `APP_URL` on Cloud Run so the dynamic A2A `AgentCard` advertises the real HTTPS URL.
4. Prefix every ephemeral Sandbox deployment and Gemini Enterprise registration with `[CI] PR-<number>-<sha7>`.
5. Validate `ge_manifest.json` and export `dist/ge-export/` via `python3 /opt/adk-factory/ge_export.py export`.
6. Prefer `ge_export.py patch --agent-name <sandbox-agent>` over per-PR `POST` creation to avoid daily Gemini Enterprise 429 quotas.
7. Never register or mutate DEV, HML, or PRD Gemini Enterprise apps from an agent container.
8. Record every created ephemeral resource in `/scion-volumes/scratchpad/sandbox-ledger.jsonl`.
