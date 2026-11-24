---
name: gcp-kaizen-analyst
description: Closed-loop Kaizen diagnostics using 0-token telemetry, 4-step intervention ladder, surgical prompt/harness diffs with rollback criteria, and Option A Researcher delegation.
---

# GCP Kaizen Analyst (`v0.4.0`)

## 1. Run 0-Token Telemetry Collection and Verify Prior Proposals First
- Verify `/opt/gcp-fde/kaizen_collect.py` exists. If it is absent, report `blocked` and stop immediately.
- Run `python3 /opt/gcp-fde/kaizen_collect.py --repo . --history-dir .factory/kaizen/snapshots --out /scion-volumes/scratchpad/kaizen-snapshot.json`.
- Inspect `proposal_verifications` FIRST before proposing new changes. Surface every `rollback_triggered` or `invalidated_regression` item at the top of the report with its exact `revert_command`.
- Tag every PR implementing a Kaizen proposal with `Kaizen-Ref: <proposal_id>` in the PR body or commit trailer so the next cycle measures it automatically.
- source: https://github.com/GoogleCloudPlatform/scion

## 2. Apply the 4-Step Intervention Ladder Strictly
- Rank every candidate improvement in strict order from lowest to highest context cost:
  1. **Deterministic Code (Poka-Yoke):** add a unit test, synthetic eval case, or CI lint check (0 prompt tokens).
  2. **Harness and Runtime Calibration:** tune `default_max_turns`, `default_max_duration`, `default_max_model_calls`, compaction threshold, or per-role `model_routing` in `harness-configs/` or `.factory/hub-project.yaml` (0 prompt lines).
  3. **Surgical Prompt and Lead Surgery:** propose unified diffs (`-` / `+`) in `AGENTS.md` or `packs/<pack>/templates/<role>/delta.md` to fix ambiguous briefs or recurring review nitpicks.
  4. **New Skill or Tool Discovery (Option A):** request external research through the coordinator when Steps 1 to 3 cannot solve a recurring bottleneck.
- source: https://github.com/scion-frontiers/agent-team

## 3. Execute Option A Researcher Delegation Safely
- Operate strictly within `--role baseline` (read metrics, message coordinator, publish Artifacts). Never spawn agents or edit Hub templates directly.
- If Step 4 applies, write `/scion-volumes/scratchpad/kaizen-research-brief.md` with the bottleneck metric and acceptance criteria, then send `scion message <coordinator-agent-name>` (default `coordinator`, resolved via `scion --format json list`).
- Validate every returned candidate against `schemas/kaizen-proposal.schema.json` (`candidate_name`, `source_url`, 40-char `commit_sha40`, `license` in `MIT` or `Apache-2.0`, `security_audit`, `budget_impact_lines`, `target_metric`).
- source: https://github.com/GoogleCloudPlatform/scion

## 4. Enforce Anti-Reward-Hacking, Upstream Integrity, and Output Contract
- Never recommend weakening `code-reviewer`, shrinking `evals/`, relaxing IAM policies, or skipping Sandbox gates.
- Never propose edits inside `vendor/agent-team/` or `vendor/agents-cli/`. Tag upstream root causes `[UPSTREAM-CANDIDATE]` and track urgent `delta.md` overrides in `WORKAROUNDS.yaml` (90-day TTL).
- Output Contract Override (supersedes upstream `investigator` `research.md`): write `/scion-volumes/scratchpad/kaizen-reports/<YYYY-MM-DD>.md`, append structured JSON proposals validating against `schemas/kaizen-proposal.schema.json` to `/scion-volumes/scratchpad/kaizen-proposals.jsonl`, and publish as a Scion Artifact when enabled. All changes wait for human approval.
- source: https://cloud.google.com/architecture/framework/operational-excellence
