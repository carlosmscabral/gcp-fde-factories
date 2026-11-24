# ADK Eval Tester Pack Delta (`packs/adk`)

1. Operate strictly with `--service-account adk-evaluator` (read and query rights only, zero write permissions on Agent Engine or GE Apps).
2. Follow `google-agents-cli-eval` and `google-agents-cli-observability` to design and audit deterministic evaluations.
3. Run `adk eval app evals/synthetic/<name>.evalset.json --config_file_path evals/eval_config.json --print_detailed_results` (or `--agent-dir agent` for brownfield repos) and fail closed when `Tests passed == 0` or `Tests failed > 0`.
4. Verify `dist/ge-export/ge_export_manifest.json` SHA-256 digests and, for A2A mode, verify `agent_card.json` satisfies A2A `v0.3.0`.
5. Emit the Contract 5 Verdict JSON under `.factory/verdicts/pr-<N>.json` via `adk-eval-runner.sh --phase evaluate`.
6. Never downgrade a live failure to `unit-test-verified` or edit `evals/` to hide a regression.
