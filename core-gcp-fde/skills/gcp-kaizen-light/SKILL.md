---
name: gcp-kaizen-light
description: Lightweight continuous improvement rules for flow metrics, hygiene issues, and graduating repeated failures into deterministic CI checks.
---

# GCP Kaizen Light

## 1. Graduate Repeated Failures to Deterministic Code
- If the same review finding or Sandbox failure occurs twice, convert the rule into a deterministic lint script, schema check, or CI gate.
- Avoid growing prompt instructions indefinitely when a Python check enforces the invariant at zero token cost.
- source: https://github.com/scion-frontiers/agent-team

## 2. Track Hygiene Work Explicitly
- Open a `priority:hygiene` issue whenever a pack skill approaches 300 lines or a `WORKAROUNDS.yaml` item approaches 90 days.
- Measure total role context across Layers 0, 1, and 2 using `scripts/budget-check.py`.
- source: https://github.com/scion-frontiers/agent-team

## 3. Clean-Room Reverse Kaizen Rule
- Before proposing a customer lesson for the central catalog, remove all customer identifiers and reproduce the issue in synthetic Argolis first.
- source: https://cloud.google.com/architecture/framework/operational-excellence
