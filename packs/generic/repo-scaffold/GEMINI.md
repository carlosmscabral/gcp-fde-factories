# Generic Software Factory Repository Contract (`packs/generic`)

This repository runs under the Google Cloud FDE Generic Software Factory (`sw-*`) built on `scion-frontiers/agent-team` (SEP).

## Operating Rules
- Read `.factory/hub-project.yaml`, `.factory/factory-profile.yaml`, `.factory/knowledge-index.yaml`, and `.factory/waves/wave-1.yaml` before planning or coding.
- Follow every rule in `.factory/knowledge/invariants.md` and `skills/<slug>-repo-conventions/SKILL.md`.
- Run `python3 /opt/generic-factory/generic_sandbox_gate.py --level 1` and `python3 /opt/gcp-fde/factory_onboard.py kp-check --repo .` before requesting pull request review.
- Require independent `sw-code-reviewer` and `sw-security-auditor` sign-off plus explicit human approval before merging to `main`.
