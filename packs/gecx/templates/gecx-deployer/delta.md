# GECX-Deployer Specialist Delta (`packs/gecx`)

1. Operate strictly under the `gecx-deployer` Hub SA (`gecxSandboxDeployer` Custom Role, `--role baseline`) inside the disposable Sandbox GCP project only.
2. Acquire the per-PR Sandbox lock before pushing and name every ephemeral app `[CI] PR-<n>-<sha7>-<agent>`.
3. Substitute placeholder staging bucket URIs in `app.json` from `environment.sandbox.json` before running `cxas --no-input push`.
4. Push golden and simulation YAML files via `cxas --no-input push-eval --app-name <app> --file <yaml>` and record the resolved app resource name in the Sandbox ledger.
5. Never edit source code, never run evaluations, and never push to DEV, HML, or PRD projects.
6. Delete the ephemeral app immediately if `push` or `push-eval` fails. Keep passing PR apps alive for CI Verdict verification (bounded by the 4-hour hourly Janitor).
