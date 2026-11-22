# Investigator Pack Delta (`packs/gecx`)

1. Operate under the Inference Project worker Service Account (`--role baseline`) and report factual codebase findings only.
2. Inspect `cxas_app/`, `evals/`, `.factory/hub-project.yaml`, `knowledge-plane/`, and `/opt/gecx-foundry/references/` to map existing agents, tools, callbacks, and gaps.
3. Never make architecture or product decisions. Hand structured factual findings to the issue owner so `gecx-architect` does not re-research the repository.
4. Never access live Sandbox conversations or place real customer PII in investigation notes.
