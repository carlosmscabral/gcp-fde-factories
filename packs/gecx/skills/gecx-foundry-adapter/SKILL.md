---
name: gecx-foundry-adapter
description: Thin Scion-native adapter invoking vendored cxas-agent-foundry v1.11.0 scripts from /opt/gecx-foundry without Claude Code interactive dependencies.
---

# GECX Foundry Adapter (Scion-Native)

This skill adapts the Apache-2.0 `cxas-agent-foundry` scripts vendored at `${GECX_FOUNDRY_DIR:-/opt/gecx-foundry}` to non-interactive Scion SEP roles.

## 1. Role Mapping (Replaces Interactive Claude Code `Agent` Tool)
- `architect`: authors `tdd.md`, `knowledge-plane/requirements.md`, and tool/callback contracts.
- `developer`: edits `cxas_app/<App>/`, callbacks, tools, and runs Level 1 offline checks only.
- `code-reviewer`: reviews diffs blindly using the active `diversity_profile` from `.factory/hub-project.yaml`.
- `gecx-deployer`: executes ephemeral Sandbox `cxas push` and `cxas push-eval --file` using the `gecx-deployer` Hub SA (`gecxSandboxDeployer` Custom Role).
- `gecx-eval-tester`: executes `cxas test-tools`, `cxas run --eval-type all --wait`, synthetic `BidiRunSession` audio checks, and REST Verdict capture using the `gecx-evaluator` Hub SA (`gecxSandboxEvaluator` Custom Role).
- source: https://github.com/GoogleCloudPlatform/cxas-scrapi/tree/f55e877638dfc07879aad4082abc35c34f18359c/.agents/skills/cxas-agent-foundry

## 2. Level 1 Offline Execution (Zero GCP Credentials)
1. Validate app structure:
   `cxas --no-input lint --app-dir cxas_app/<App>`
2. Synchronize local callback code and create required `test.py` symlinks:
   `python3 "${GECX_FOUNDRY_DIR:-/opt/gecx-foundry}/scripts/sync-callbacks.py" --from-local cxas_app/<App>`
3. Execute callback unit tests offline (CLI injects `CallbackContext` and `LlmRequest`):
   `cxas --no-input test-callbacks --app-dir evals/callback_tests`
- source: canaries/gecx/cxas_1.11.0_cli_contract.json

## 3. Level 2 Live Sandbox Execution (Split-SA Workflow)
1. Never call `cxas ci-test` (single-SA, skips teardown, applies `--filter-auto-metrics`).
2. Never combine `--eval-type` with `--min-pass-rate` or `--runs` on `cxas-scrapi 1.11.0` (upstream bug `WK-001` in `cli/main.py:596`).
3. Invoke the split-SA runner (`packs/gecx/scripts/gecx-eval-runner.sh`), which runs:
   - Deployer SA: `cxas --no-input push` + `cxas --no-input push-eval --app-name <app> --file <yaml>`
   - Evaluator SA: `cxas --no-input test-tools --app-name <app> --test-file <yaml>` + `cxas --no-input run --app-name <app> --eval-type all --wait`
   - Evaluator SA: independent `GET /v1beta/<app>/evaluationRuns` readback enforcing `totalCount > 0` and `failedCount == 0`.
- source: canaries/gecx/cxas_1.11.0_cli_contract.json

## 4. Using Foundry Reference Docs and Analysis Scripts
- Read API schemas from `/opt/gecx-foundry/references/api-schemas/` when editing `app.json`, tools, or evaluations.
- Use `/opt/gecx-foundry/scripts/triage-results.py` and `/opt/gecx-foundry/scripts/calculate-coverage.py` against downloaded eval reports. Never invoke interactive `configure.py` or `setup.sh` inside headless agents.
- source: https://github.com/GoogleCloudPlatform/cxas-scrapi/tree/f55e877638dfc07879aad4082abc35c34f18359c/.agents/skills/cxas-agent-foundry
