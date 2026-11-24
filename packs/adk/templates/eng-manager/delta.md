# Engineering Manager Pack Delta (`packs/adk`)

1. Collapse implementation phases whenever the agreed design touches one agent package or tool module; dispatch a single `adk-developer` and blind `adk-code-reviewer`.
2. Freeze tool schemas, `ge_manifest.json` contract, and `evals/` targets in the brief before slicing parallel developer phases.
3. Read `diversity_profile` and `model_routing` from `.factory/hub-project.yaml` and pass `--harness-config adk-<harness> --model <model> --thinking-level <N>` on every `scion start` across every `adk-developer` and `adk-code-reviewer` pair.
4. Spawn `adk-*` prefixed templates exclusively and never delegate `--role full` to child workers.
5. Append one JSON audit line to `/scion-volumes/scratchpad/kaizen-events.jsonl` whenever an Andon Cord escalation or worker stall occurs.
6. Confirm offline pytest, root `Dockerfile` contract check, and `ge_export.py validate` pass before handing off to `adk-deployer` and `adk-eval-tester`.
