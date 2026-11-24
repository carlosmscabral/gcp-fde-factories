# Coordinator Pack Delta (`packs/gecx`)

1. Disable periodic 15-to-30-minute coordinator sweeps. Wake only on external Delta Watcher triggers, explicit human messages, scheduled `weekly-kaizen` triggers, or `gecx-kaizen-analyst` Option A research briefs.
2. Apply Preston sizing rules from `software-engineering-process`: use Depth-1 (`gecx-developer`, `gecx-code-reviewer`, `gecx-deployer`, `gecx-eval-tester`) for Small changes, and Depth-3 (dedicated issue owner with `-t gecx-coordinator --role full`, `gecx-investigator`, `gecx-architect`, `gecx-eng-manager --role full`) for Chunky or Large changes.
3. Spawn `gecx-*` prefixed templates (never bare upstream names) and pass `--role full` only to sub-coordinators and `gecx-eng-manager`.
4. Read `diversity_profile`, `harnesses`, and `model_routing` from `.factory/hub-project.yaml` and pass `--harness-config gecx-<harness> --model <tier-or-id> --thinking-level <N>` on every `scion start` (using Scion generic tiers `small`/`medium`/`large`/`extra-large` or explicit model IDs across Antigravity + Claude in `cross-vendor`, or two Antigravity sub-agents with distinct Gemini models in `cross-model`).
5. Route Sandbox deploy requests exclusively to `gecx-deployer` (`--service-account gecx-deployer`) and live evaluation requests exclusively to `gecx-eval-tester` (`--service-account gecx-evaluator`).
6. Never assign `gecx-deployer` or `gecx-eval-tester` SAs to `gecx-coordinator`, `gecx-eng-manager`, `gecx-architect`, `gecx-developer`, or `gecx-code-reviewer`.
7. Require a human PR approval on every pull request in v1. Never auto-merge to `main`.
8. Escalate immediately if a PR changes telephony, SIP, SBC, VAIC, DTMF, or CCaaS surfaces and require the `not-verifiable-in-sandbox` verdict level.
9. When `gecx-kaizen-analyst` requests Option A external skill discovery via `scion msg`, spawn a bounded `gecx-researcher` (`--role baseline`), return its Candidate Skill Sheet to `gecx-kaizen-analyst`, and retire the researcher upon delivery.
