# Test Engineer Pack Delta (`packs/adk`)

1. Build deterministic offline unit tests with fake tool backends and validate the root `Dockerfile` container contract in an isolated subprocess.
2. Author synthetic `adk eval` datasets (`evals/`) covering both `tool_trajectory_avg_score` and `final_response_match_v2` without real customer PII.
3. Add contract tests validating `ge_manifest.json`, `ge_registration_payload.json`, and A2A `agent_card.json` outputs from `ge_export.py`.
4. Graduate any defect that appears twice in code review or Sandbox runs into a permanent deterministic pytest check.
5. Keep all offline tests passing under zero network egress (`--network=none`).
