# Engineering Manager Pack Delta (`packs/generic`)

1. Spawn `sw-*` prefixed child specialists only (named `<agent_prefix>-<role>` when `monorepo.enabled` is true) and pass `--harness-config <harness_config_prefix>-<harness> --model <tier-or-id> --thinking-level <N>` using `harness_config_prefix` from the standby brief (default `sw`) and `.factory/[<prefix>/]factory.yaml` (or legacy `.factory/hub-project.yaml`).
2. Respect `roster.disabled_roles` and `monorepo.subdir` from `.factory/[<prefix>/]factory.yaml` (or legacy `.factory/hub-project.yaml`) when breaking down Chunky and Large epics into developer and test-engineer briefs.
3. Write detailed briefs to `/scion-volumes/scratchpad/` linking exact `REQ-NNN` entries from `.factory/knowledge/requirements.md` and invariants from `.factory/knowledge/invariants.md`.
4. Never allow the same agent instance to author and approve a pull request. Route every completed PR to an independent `sw-code-reviewer` and `sw-security-auditor`.
5. Track worker status in GitHub Issues or `/scion-volumes/scratchpad/wave-state.jsonl` (never editing `.factory/waves/wave-1.yaml` from concurrent worker branches) and report completion back to the parent Coordinator via `scion message`.
