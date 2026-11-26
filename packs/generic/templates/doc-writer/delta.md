# Doc Writer Pack Delta (`packs/generic`)

1. Maintain `.factory/knowledge/{requirements.md,invariants.md,glossary.md,decisions/README.md}` and repository documentation without duplicating pre-existing customer ADRs.
2. Keep documentation concise, active-voice, and aligned with canonical terms in `.factory/knowledge/glossary.md`.
3. Run `python3 /opt/gcp-fde/factory_onboard.py kp-check --repo .` after every documentation or Knowledge Plane edit to confirm zero broken links.
