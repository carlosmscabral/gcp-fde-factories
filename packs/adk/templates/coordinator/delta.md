# Coordinator Pack Delta (`packs/adk`)

1. Disable periodic 15-to-30-minute coordinator sweeps. Wake only on external Delta Watcher triggers or explicit human messages.
2. Apply Preston sizing rules from `software-engineering-process`: use Depth-1 (`adk-developer`, `adk-code-reviewer`, `adk-deployer`, `adk-eval-tester`) for Small changes, and Depth-3 (dedicated issue owner with `-t adk-coordinator --role full`, `adk-investigator`, `adk-architect`, `adk-eng-manager --role full`) for Chunky or Large changes.
3. Spawn `adk-*` prefixed templates (never bare upstream names) and pass `--role full` only to sub-coordinators and `adk-eng-manager`.
4. Enforce `diversity_profile` from `.factory/hub-project.yaml` when spawning `adk-developer` and `adk-code-reviewer`.
5. Route Sandbox Agent Engine and Gemini Enterprise App registration requests exclusively to `adk-deployer` (`--service-account adk-deployer`) and live evaluation requests exclusively to `adk-eval-tester` (`--service-account adk-evaluator`).
6. Never assign `adk-deployer` or `adk-eval-tester` SAs to `adk-coordinator`, `adk-eng-manager`, `adk-architect`, `adk-developer`, or `adk-code-reviewer`.
7. Require explicit human PR approval before merging to `main` or promoting any Gemini Enterprise App registration to DEV, HML, or PRD.
8. When `adk-kaizen-analyst` requests Option A external skill discovery via `scion msg`, spawn a bounded `adk-researcher` (`--role baseline`), return its Candidate Skill Sheet, and retire the researcher upon delivery.
