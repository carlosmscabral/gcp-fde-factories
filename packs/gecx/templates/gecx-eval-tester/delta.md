# GECX-Eval-Tester Specialist Delta (`packs/gecx`)

1. Operate strictly under `gecxSandboxEvaluator` SA (`--role baseline`, zero app write permissions and zero conversation/Insights read access).
2. Run `cxas --no-input test-tools --app-name <app> --test-file <yaml>` against the deployed ephemeral app.
3. Run `cxas --no-input run --app-name <app> --eval-type all --wait` (avoiding `--eval-type` + `--min-pass-rate` per `WK-001` in `WORKAROUNDS.yaml`).
4. When audio scenarios exist, execute synthetic `Sessions.async_bidi_run_session` checks (`capture_agent_audio=True`).
5. Read `GET /v1beta/<app>/evaluationRuns` directly, assert `totalCount > 0` and `failedCount == 0`, and emit a Verdict JSON matching `schemas/verdict.schema.json`.
6. Never claim `live-gcp-verified` when zero evaluations ran or when telephony/SIP/SBC/VAIC/DTMF/CCaaS surfaces changed.
