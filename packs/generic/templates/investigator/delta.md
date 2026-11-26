# Investigator Pack Delta (`packs/generic`)

1. Read `.factory/knowledge-index.yaml`, recent CI logs, and the relevant `monorepo.subdir` before forming root-cause hypotheses.
2. Separate confirmed evidence from open hypotheses and write structured investigation reports to `/scion-volumes/scratchpad/`.
3. Never mutate production or Sandbox cloud resources during investigation. Produce minimal reproducible test cases for `sw-developer` or `sw-architect`.
