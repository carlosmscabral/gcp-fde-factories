---
name: gcp-kaizen-light
description: Lightweight continuous improvement rules for flow metrics, hygiene issues, and graduating repeated failures into deterministic CI checks.
---

# GCP Kaizen Light

## 1. Graduate Repeated Failures to Deterministic Code
- If the same review finding or Sandbox failure occurs twice, convert the rule into a deterministic lint script, schema check, or CI gate.
- Avoid growing prompt instructions indefinitely when a Python check enforces the invariant at zero token cost.
- source: https://github.com/scion-frontiers/agent-team

## 2. Track Hygiene Work and Lead Events Explicitly
- Open a `priority:hygiene` issue whenever an authored skill approaches 300 lines or a `WORKAROUNDS.yaml` entry approaches 90 days.
- Run the pack verification gate (or `./build.sh --check <pack-dir>` in the factory catalog repo) before proposing skill or prompt edits.
- When a coordinator or engineering manager triggers an Andon Cord escalation or resolves a stall, append one JSON line (`{"ts_utc","agent","event","summary"}`) to `/scion-volumes/scratchpad/kaizen-events.jsonl`.
- source: https://github.com/scion-frontiers/agent-team

## 3. Clean-Room Reverse Kaizen Rule
- Before proposing a customer lesson for the central catalog, remove all customer identifiers and reproduce the issue in a synthetic project first.
- source: https://cloud.google.com/architecture/framework/operational-excellence
