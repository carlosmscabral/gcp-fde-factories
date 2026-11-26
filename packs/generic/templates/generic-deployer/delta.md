# Generic Deployer Pack Delta (`packs/generic`)

1. Operate strictly with `--service-account sw-deployer` inside the disposable Sandbox project only.
2. Check `mode` and `deploy_target` in `.factory/hub-project.yaml` first. If `mode` is `ci-only` or `deploy_target` is `none`, abort without calling cloud APIs and report back to the Coordinator.
3. Deploy ephemeral Sandbox revisions for `cloud-run`, `gke`, or `custom` targets using `ci-pr-<number>-<sha7>` / `[CI] PR-<number>-<sha7>` naming and mandatory labels `factory_ci=true`, `pr=pr-<N>`, and `commit=<sha7>` so `sandbox_janitor.py` sweeps expired services cleanly.
4. Never deploy to or mutate customer DEV, HML, or PRD projects from an agent container.
5. Record every created ephemeral resource URI and timestamp in `/scion-volumes/scratchpad/sandbox-ledger.jsonl` for teardown hygiene.
