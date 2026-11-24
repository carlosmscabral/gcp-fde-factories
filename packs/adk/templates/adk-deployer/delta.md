# ADK Sandbox Deployer Pack Delta (`packs/adk`)

1. Operate exclusively under the Sandbox Deployer SA (`--service-account adk-deployer`) targeting the disposable Sandbox GCP project.
2. Acquire the per-PR lock and deploy ephemeral Agent Engine resources prefixed with `[CI] PR-<n>-<sha7>-<agent>` after passing Level 1 checks.
3. Generate the deterministic Gemini Enterprise export bundle (`dist/ge-export/`) with `ge_export.py export` and register ephemeral `[CI]` agents ONLY in the Sandbox Gemini Enterprise App.
4. Record every created ephemeral ReasoningEngine and Sandbox GE agent resource in `/scion-volumes/scratchpad/sandbox-ledger.jsonl`.
5. Never deploy to DEV, HML, or PRD projects or production Gemini Enterprise Apps.
6. Clean up failed or intermediate ephemeral resources in `finally`; keep passing PR resources alive only until CI verification and Janitor teardown complete.
