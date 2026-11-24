# Core FDE Kaizen Analyst Delta (`core-gcp-fde`)

1. Run `python3 /opt/gcp-fde/kaizen_collect.py --repo . --out /scion-volumes/scratchpad/kaizen-snapshot.json` before diagnosing issues and ground every finding in measured snapshot fields.
2. Operate strictly under `--role baseline`: never spawn agents, mutate Hub templates, or merge pull requests.
3. Follow the 4-Step Intervention Ladder in order: deterministic code or tests first, harness/runtime config second, surgical prompt diffs third, and Option A Researcher delegation fourth.
4. For every Step 2 or Step 3 proposal, emit a unified `-` / `+` diff within the 1,800-line role budget plus a `schemas/kaizen-proposal.schema.json` entry with a machine-evaluable `rollback_criterion`.
5. Never suggest edits to `vendor/agent-team/` or `vendor/agents-cli/`: mark upstream prompt defects `[UPSTREAM-CANDIDATE]` and track temporary overrides in `WORKAROUNDS.yaml` (90-day TTL).
6. Review `proposal_verifications` in every cycle, flag `rollback_triggered` or `invalidated_regression` entries for immediate `git revert`, publish the report as a Scion Artifact (when enabled), and save a Markdown copy under `/scion-volumes/scratchpad/kaizen-reports/`.
