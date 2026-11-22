# Test Engineer Pack Delta (`packs/gecx`)

1. Operate under the Inference Project worker Service Account (`--role baseline`) and never run live `cxas push` calls.
2. Design deterministic Level 1 offline tests across `evals/callback_tests/`, `evals/tool_tests/`, `evals/goldens/`, and fake-backed `pytest` suites.
3. For bug fixes, write a failing offline test first (Prove-It pattern) before verifying the fix.
4. Use synthetic fixtures only. Never include real customer PII, real CPF values, real phone numbers, or real audio files.
5. Flag every pull request that modifies `evals/` alongside `cxas_app/` so the coordinator requests the human `eval-change-approved` label.
