# ADR-006: Vertex AI Default, Generic Tiers, and Fail-Closed Claude

- **Status:** Accepted
- **Date:** 2026-11-24
- **Invariants:** [INV-09](../INVARIANTS.md#inv-09-vertex-ai-default-and-generic-model-tiers), [INV-10](../INVARIANTS.md#inv-10-fail-closed-claude-on-vertex-preflight)

## Context

Enterprise Google Cloud customers require billing consolidation, VPC Service Controls, and data residency through Vertex AI rather than personal API keys.
Hardcoding vendor-specific model version strings across templates, skills, and scripts creates rapid drift when newer frontier models release.
Upstream Scion v0.4 introduced generic model tier aliases (`extra-large`, `large`, `medium`, `small`) mapped centrally to concrete models.
Additionally, enabling `CLAUDE_CODE_USE_VERTEX=1` without `ANTHROPIC_VERTEX_PROJECT_ID` or Model Garden opt-in causes silent runtime failures inside Claude containers.

## Decision

1. Default all factory harness configs to first-party Vertex AI routing:
   - `core-gcp-fde/harness-configs/antigravity-vertex.yaml`: `auth_selected_type: vertex-ai`, `GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_LOCATION=global`.
   - `core-gcp-fde/harness-configs/claude-vertex.yaml`: `CLAUDE_CODE_USE_VERTEX=1`, `CLOUD_ML_REGION=global`, `ANTHROPIC_VERTEX_PROJECT_ID` set to the inference project.
2. Centralize generic tier routing (`small`, `medium`, `large`, `extra-large`) and `thinking_level` (`0-100`) resolution in `scripts/lib/model_routing.py` and `deploy/03-hub-bootstrap/parse_hub_project.py`.
3. Reference generic tiers in templates, skills, and operational guides instead of hardcoded model version strings while allowing optional per-role overrides in `.factory/hub-project.yaml`.
4. Keep `deploy/03-hub-bootstrap/bootstrap-hub-project.sh` configurable via `--vertex-location`, `--vertex-claude-region`, and `--inference-project`.
5. Enforce a fail-closed check in `scripts/lib/model_routing.py` and `deploy/03-hub-bootstrap/parse_hub_project.py`: reject `cross-vendor` or any `claude-vertex` role whenever `harnesses.claude_model_garden_enabled` is `false`, and fail closed in `deploy/03-hub-bootstrap/bootstrap-hub-project.sh` if `ANTHROPIC_VERTEX_PROJECT_ID` is empty.

## Consequences

- Concrete frontier models evolve automatically with upstream Scion releases without editing pack templates.
- Zero personal Anthropic or Gemini API keys enter customer environments by default.
- Misconfigured Claude Vertex settings fail fast at bootstrap time instead of crashing live agent pods.

## Enforcement

- `core-gcp-fde/harness-configs/antigravity-vertex.yaml`
- `core-gcp-fde/harness-configs/claude-vertex.yaml`
- `scripts/lib/model_routing.py`
- `deploy/03-hub-bootstrap/parse_hub_project.py`
- `deploy/03-hub-bootstrap/bootstrap-hub-project.sh`
- `tests/test_release_kit_build.py`
