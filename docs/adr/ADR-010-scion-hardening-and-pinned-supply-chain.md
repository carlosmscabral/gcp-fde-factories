# ADR-010: Scion Hub Hardening and Pinned Supply Chain

- **Status:** Accepted
- **Date:** 2026-11-22
- **Invariants:** [INV-06](../INVARIANTS.md#inv-06-digest-pinned-runtime-and-harness-images), [INV-14](../INVARIANTS.md#inv-14-pinned-scion-release-and-fail-closed-hub-iam)

## Context

Floating upstream `main` references break reproducible deployments and introduce unverified supply-chain changes.
Default Scion Hub settings can allow broad GCP metadata access or silently skip IAM verification if not explicitly hardened.
On Lite Single-VM installations without HTTPS ingress, binding `0.0.0.0` under `--hosted` mode fails Scion startup validation.

## Decision

1. Pin the tested upstream Scion tag (`v0.4.0-preview.3`) and release tarball SHA-256 checksum in `compat.yaml` and `deploy/02-factory-runtime/lite-vm/variables.tf`.
2. Enforce strict Hub IAM controls in both VM and GKE runtime configurations:
   - `default_gcp_identity_mode: "block"`
   - `server.hub.gcp_iam_check_mode: "enforce"`
   - `server.hub.gcp_iam_deny_unknown_policy: "fail-closed"`
3. Provision Lite Single-VM instances with Shielded VM enabled, OS Login enabled, and zero public IP addresses (outbound via Cloud NAT, operator access via IAP SSH).
4. Bind Lite Single-VM `--host` to `127.0.0.1` when `hub_public_url` is empty, and `0.0.0.0` only when an HTTPS `hub_public_url` is set.
5. Namespace all Scion templates, skills, and harness configs with `<pack_prefix>-` so multiple packs coexist safely on one Hub.

## Consequences

- Operators must hold `roles/iam.serviceAccountUser` on each assignable Service Account before assigning it to an agent.
- Agent containers without an explicit Service Account receive zero GCP credentials (`block` mode).
- Every installed Scion binary and container image is cryptographically verified before execution.

## Enforcement

- `compat.yaml`
- `deploy/02-factory-runtime/lite-vm/{vm.tf,cloud-init.tftpl,variables.tf}`
- `deploy/03-hub-bootstrap/bootstrap-hub-project.sh`
- `tests/test_terraform_and_scaffold_parity.py`
