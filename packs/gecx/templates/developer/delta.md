# Developer Pack Delta (`packs/gecx`)

1. Operate strictly under the Inference Project worker Service Account (`--role baseline`). Never attempt `cxas push`, `cxas delete`, or live Sandbox API calls.
2. Run all Level 1 offline checks (`cxas lint`, `sync-callbacks.py --from-local`, `cxas test-callbacks`, and fake-backed `pytest`) before reporting ready for review.
3. Keep `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` identical whenever updating repository rules.
4. Never modify `evals/` in the same PR as `cxas_app/` without flagging the coordinator to request the human `eval-change-approved` label.
5. Never place real customer PII, real phone numbers, or real audio recordings inside `evals/` or fixtures.
