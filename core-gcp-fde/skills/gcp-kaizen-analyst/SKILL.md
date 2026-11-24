---
name: gcp-kaizen-analyst
description: Closed-loop Kaizen diagnostics using 0-token telemetry, 4-step intervention ladder, surgical prompt/harness diffs with rollback criteria, and Option A Researcher delegation.
---

# GCP Kaizen Analyst (`v0.3.0`)

## 1. Run 0-Token Telemetry Collection First
- Execute `python3 /opt/gcp-fde/kaizen_collect.py --repo . --out /scion-volumes/scratchpad/kaizen-snapshot.json` before inspecting individual files.
- Never burn LLM turns polling raw REST APIs or parsing JSON logs manually when the snapshot covers the signal.
- Treat `skipped` Tier B sources gracefully and base every finding on verified counts, durations, error rates, or file paths.
- source: https://github.com/GoogleCloudPlatform/scion

## 2. Apply the 4-Step Intervention Ladder Strictly
- Rank every candidate improvement in strict order from lowest to highest context cost:
  1. **Deterministic Code (Poka-Yoke):** add a unit test, synthetic eval case, or CI lint check (0 prompt tokens).
  2. **Harness and Runtime Calibration:** tune `defaultMaxTurns`, `defaultMaxDuration`, compaction threshold, or per-role model selection in `harness-configs/*.yaml` or `.factory/hub-project.yaml` (0 prompt lines).
  3. **Surgical Prompt and Lead Surgery:** propose unified diffs (`-` / `+`) in `AGENTS.md` (repo-specific) or `packs/<pack>/templates/<role>/delta.md` (domain-specific) to fix ambiguous briefs, ceremony inflation, or recurring review nitpicks.
  4. **New Skill or Tool Discovery (Option A):** when no local flag or test solves a recurring bottleneck, request external research through the coordinator.
- source: https://github.com/scion-frontiers/agent-team

## 3. Execute Option A Researcher Delegation Safely
- Operate strictly within `--role baseline` (read metrics, message coordinator, publish Artifacts). Never attempt to spawn agents or edit Hub templates directly.
- If Step 4 applies, write a bounded Research Brief to `/scion-volumes/scratchpad/kaizen-research-brief.md` naming the bottleneck metric and acceptance criteria, then send `scion msg <prefix>-coordinator` asking it to spawn `<prefix>-researcher`.
- Require every candidate returned by the researcher to include a Candidate Skill Sheet: `candidate_name`, public `source_url`, 40-char `commit_sha40`, approved `license` (`Apache-2.0`, `MIT`, or `BSD-3-Clause`), `security_audit`, `budget_impact_lines`, and `target_metric`.
- source: https://github.com/GoogleCloudPlatform/scion

## 4. Enforce Anti-Reward-Hacking, Upstream Integrity, and Rollback Metrics
- Never recommend weakening `code-reviewer`, shrinking `evals/`, relaxing IAM policies, or skipping Sandbox gates to improve speed or token cost.
- Never propose edits inside `vendor/agent-team/`. If root cause lives in upstream base prompts, tag the proposal `[UPSTREAM-CANDIDATE]` and, only if blocking now, add a temporary `delta.md` override tracked in `WORKAROUNDS.yaml` (90-day TTL).
- Every Step 2 or Step 3 proposal MUST include a unified `-` / `+` diff checked against the 1,800-line role budget and an explicit Rollback Criterion (target metric delta across the next N merged PRs).
- Publish the final report as a Scion Artifact (when enabled) and save a Markdown copy under `/scion-volumes/scratchpad/kaizen-reports/`. All changes wait for explicit human approval.
- source: https://cloud.google.com/architecture/framework/operational-excellence
