# ADK Sandbox Evaluator Pack Delta (`packs/adk`)

1. Operate exclusively under the Sandbox Evaluator SA (`--service-account adk-evaluator`) with zero write permissions on Sandbox apps or Agent Engine resources.
2. Execute `adk eval --config_file_path evals/eval_config.json` and probe the ephemeral `[CI]` ReasoningEngine or A2A `/.well-known/agent-card.json` endpoint.
3. Verify the exported Gemini Enterprise bundle (`dist/ge-export/ge_registration_payload.json` and SHA-256 manifest) matches the current PR commit and `evals/` tree hash.
4. Emit a schema-valid `verdict.json` conforming to `schemas/verdict.schema.json`; fail closed on zero eval cases or missing live probes.
5. Label changes touching interactive 3LO OAuth UI or private on-prem PSC endpoints honestly as `not-verifiable-in-sandbox`.
6. Never edit `agent/` code or modify `evals/` expectations during evaluation runs.
