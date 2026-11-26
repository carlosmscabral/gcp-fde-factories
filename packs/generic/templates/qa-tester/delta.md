# QA Tester Pack Delta (`packs/generic`)

1. Run live Sandbox smoke and end-to-end checks via `python3 /opt/generic-factory/generic_sandbox_gate.py --level 2` against ephemeral `[CI]` deployments only.
2. When `deploy_target` is `none`, verify CLI or library acceptance criteria locally without invoking cloud deploy endpoints.
3. Map every verification result directly to `REQ-NNN` acceptance criteria in `.factory/knowledge/requirements.md` and list `not_verifiable_in_sandbox` boundaries honestly.
4. Write verification evidence to `/scion-volumes/scratchpad/` so the Coordinator and human reviewers can inspect exact command outputs.
