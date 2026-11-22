# Coordinator Pack Delta (`packs/gecx`)

1. Disable periodic 15-to-30-minute coordinator sweeps. Wake only on external Delta Watcher triggers or explicit human messages.
2. Apply Preston sizing rules from `software-engineering-process`: use Depth-1 (`gecx-developer`, `gecx-code-reviewer`, `gecx-deployer`, `gecx-eval-tester`) for Small changes, and Depth-3 (dedicated issue owner with `-t gecx-coordinator --role full`, `gecx-investigator`, `gecx-architect`, `gecx-eng-manager --role full`) for Chunky or Large changes.
3. Spawn `gecx-*` prefixed templates (never bare upstream names) and pass `--role full` only to sub-coordinators and `gecx-eng-manager`.
4. Enforce `diversity_profile` from `.factory/hub-project.yaml` when spawning `gecx-developer` and `gecx-code-reviewer`.
5. Route Sandbox deploy requests exclusively to `gecx-deployer` (`--service-account gecx-deployer`) and live evaluation requests exclusively to `gecx-eval-tester` (`--service-account gecx-evaluator`).
6. Never assign `gecx-deployer` or `gecx-eval-tester` SAs to `gecx-coordinator`, `gecx-eng-manager`, `gecx-architect`, `gecx-developer`, or `gecx-code-reviewer`.
7. Require a human PR approval on every pull request in v1. Never auto-merge to `main`.
8. Escalate immediately if a PR changes telephony, SIP, SBC, VAIC, DTMF, or CCaaS surfaces and require the `not-verifiable-in-sandbox` verdict level.
