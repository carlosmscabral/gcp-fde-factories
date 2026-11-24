# Engineering Manager Pack Delta (`packs/gecx`)

1. Operate under the Inference Project worker Service Account (`--service-account factory-worker`) with `--role full` so you can create and supervise implementation subtrees.
2. Always spawn `gecx-*` prefixed templates (`gecx-developer`, `gecx-code-reviewer`, `gecx-test-engineer`, `gecx-security-auditor`, `gecx-deployer`, `gecx-eval-tester`) with `--role baseline`.
3. Collapse ceremony on trivial phases: if a phase touches one sub-agent or one tool, dispatch a single `gecx-developer` and one blind `gecx-code-reviewer`.
4. Sequence shared CX Agent Studio files (`app.json`, shared callbacks, shared tools, `AGENTS.md`) on a single dedicated `gecx-developer` before fanning out parallel sub-agent workstreams.
5. Read `diversity_profile` and `model_routing` from `.factory/hub-project.yaml` and pass `--harness-config gecx-<harness> --model <model> --thinking-level <N>` on every `scion start` so each `gecx-code-reviewer` runs on a distinct model or vendor from `gecx-developer`.
6. Suspend idle developers while blind reviews run (`scion suspend`) and delete completed reviewers after durable handoff.
7. Never assign `gecx-deployer` or `gecx-eval-tester` SAs to coders or reviewers. Route Sandbox deploys only to `gecx-deployer` and live evals only to `gecx-eval-tester`.
8. Merge reviewed feature branches into the feature integration branch only. Never auto-merge into `main` (human approval and `GECX Verdict Gate` remain mandatory).
