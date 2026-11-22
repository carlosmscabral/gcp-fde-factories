# gcp-fde-factories

Reusable autonomous software factory packs built on Google Cloud Scion (`v0.4.0-preview.3`) and `scion-frontiers/agent-team` for Google Cloud Forward Deployed Engineers (FDEs).

## Scope (Phase 1a)

- **Active Pilot Pack:** `packs/gecx` (Google Cloud Customer Engagement Suite / CX Agent Studio, text and synthetic `BidiRunSession` audio).
- **Frozen Skeletons:** `packs/adk` and `packs/agent-platform` remain frozen until `packs/gecx` completes Phase 1b live validation in Argolis.
- **Template Starter:** `packs/_template-pack` defines the canonical skeleton for future domain packs.

## Quickstart

1. Install Python 3.12 dependencies into `.venv`:
   ```bash
   uv venv .venv --python 3.12
   uv pip install --python .venv/bin/python -e ".[dev]"
   ```
2. Run all static contract, lockfile, context-budget, and public sanitization checks:
   ```bash
   ./build.sh --check packs/gecx
   ```
3. Run the unit test suite:
   ```bash
   ./build.sh --test
   ```
4. Build a self-contained offline Release Kit for customer delivery:
   ```bash
   ./build.sh --release-kit packs/gecx --out /tmp/gecx-kit
   ```

## Three-Stage Customer Deployment

1. **Stage 01 (`deploy/01-landing-zone`):** Customer Platform/SecOps provisions networking (custom or Shared VPC), Artifact Registry, 6 Service Accounts with additive IAM, 3 explicit non-wildcard CES Custom Roles, and the Inference Project budget. Exports `landing-zone-outputs.json`.
2. **Stage 02 (`deploy/02-factory-runtime`):** Platform or FDE deploys either `lite-vm` (Shielded VM with zero public IP) or `ha-gke` (delegating to the official Scion Terraform module).
3. **Stage 03 (`deploy/03-hub-bootstrap`):** Customer principal runs `bootstrap-hub-project.sh` (`preflight -> plan -> backup -> apply`) and starts `coordinator` on Day 1.

## Architecture Principles

- Every external skill URI pins to a 40-character Git commit SHA and SHA-256 digest in `skills.lock`.
- Every specialist template composes deterministically at build time from `base_role` plus a bounded pack delta.
- Every Release Kit ships zero external URIs and supports both pre-built mirror staging (`stage-release-kit.sh`) and internal rebuild (`cloudbuild.yaml`).
- Every customer PR Verdict passes deterministic verification against the CES `evaluationRuns` API in GitHub Actions.
