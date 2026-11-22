# Coordinator Pack Delta (`packs/gecx`)

1. Disable periodic 15-to-30-minute coordinator sweeps. Wake only on external Delta Watcher triggers or explicit human messages.
2. Enforce `diversity_profile` from `.factory/hub-project.yaml` when spawning `developer` and `code-reviewer`.
3. Route Sandbox deploy requests exclusively to `gecx-deployer` (`--service-account gecx-deployer`) and live evaluation requests exclusively to `gecx-eval-tester` (`--service-account gecx-evaluator`).
4. Never assign `gecx-deployer` or `gecx-eval-tester` SAs to `developer`, `architect`, or `code-reviewer`.
5. Require a human PR approval on every pull request in v1. Never auto-merge to `main`.
6. Escalate immediately if a PR changes telephony, SIP, SBC, VAIC, DTMF, or CCaaS surfaces and require the `not-verifiable-in-sandbox` verdict level.
