# gcp-fde-factories

**Reusable Autonomous Software Factories for Google Cloud Forward Deployed Engineers (FDEs)** — built on **Google Cloud Scion (`v0.4.0-preview.3`)**, **`scion-frontiers/agent-team` (SEP)**, **Vertex AI-first generic model tiers**, **split-SA Sandbox verification**, **closed-loop Kaizen**, and **zero-overwrite Brownfield onboarding**.

> **Release `contrafile` (`v0.6.0`):** Adds the lean **`packs/generic`** (`sw-*`) software factory pack for arbitrary brownfield/greenfield repositories, declarative 6-pillar `/grill-me` onboarding with `--emit-draft`, evidence-based SEP role curation, zero-clobber Knowledge Plane (`.factory/knowledge/*`, `.factory/waves/wave-1.yaml`, `kp-check`), monorepo scoping, and idempotent PO-gated standby Coordinator launch in Stage 03 (`ADR-016`), building on `bife` (`v0.5.0`) 3-project cross-project isolation, keyless WIF, native `agents-cli` ADK (`ADR-014`), cognitive brownfield adaptation (`ADR-015`), and closed-loop Kaizen ([Enterprise GCP Prerequisites Checklist](deploy/ENTERPRISE_PREREQUISITES.md) | [Hillclimbing Qualification Ledger](docs/HILLCLIMBING_CHARTER.md)).

---

## 1. Big Picture — 4-Layer Architecture & 3-Stage Delivery

Every factory separates **immutable upstream engineering roles**, **shared FDE governance**, **domain packs**, and **customer repository overlays** so you never fork upstream templates or hardcode customer rules inside the catalog.

```mermaid
flowchart TB
    subgraph L0["Layer 0 — Vendored Upstream (Read-Only, SHA-40 Pinned)"]
        SEP["vendor/agent-team/<br/>13 SEP Roles + 5 Skills"]
        AGCLI["vendor/agents-cli/<br/>7 ADK Skills v1.15.0"]
    end

    subgraph L1["Layer 1 — Shared FDE Core (core-gcp-fde/)"]
        CORE_SK["5 Core Skills<br/>guardrails, sandbox, kaizen, onboard"]
        CORE_HC["Vertex AI Harnesses<br/>antigravity-vertex & claude-vertex"]
        CORE_TOOLS["0-Token CLI Tools<br/>kaizen_collect.py & factory_onboard.py"]
    end

    subgraph L2["Layer 2 — Domain Factory Packs (packs/)"]
        GECX["packs/gecx (v0.5.0)<br/>16 templates • 11 skills<br/>CX Agent Studio + Audio"]
        ADK["packs/adk (v0.5.0)<br/>16 templates • 18 skills<br/>ADK 2.15 + Dockerfile + GE App"]
        GEN["packs/generic (v0.6.0)<br/>15 templates (sw-*) • 10 skills<br/>Any Software / Monorepo / CLI"]
        TPL["packs/_template-pack<br/>Starter Skeleton"]
    end

    subgraph L3["Layer 3 — Customer Repo Overlay (.factory/)"]
        OV["hub-project.yaml • factory-profile.yaml<br/>knowledge-index.yaml • knowledge/* • waves/wave-1.yaml<br/>Conditional Dockerfile.customer"]
    end

    subgraph DELIV["3-Stage Customer GCP Delivery (deploy/)"]
        S1["Stage 01: Landing Zone<br/>VPC, AR, 4-10 SAs, Custom Roles, WIF"]
        S2["Stage 02: Factory Runtime<br/>lite-vm (Shielded) or ha-gke (Preview)"]
        S3["Stage 03: Hub Bootstrap<br/>stage-release-kit -> bootstrap-hub-project -> Standby Coordinator"]
    end

    SEP --> CORE_SK
    AGCLI --> CORE_TOOLS
    CORE_SK --> GECX
    CORE_TOOLS --> ADK
    CORE_SK --> GEN
    GECX -->|"./build.sh --release-kit"| S3
    ADK -->|"./build.sh --release-kit"| S3
    GEN -->|"./build.sh --release-kit"| S3
    S1 -->|"landing-zone-outputs.json"| S2
    S2 -->|"Healthy Hub via IAP"| S3
    OV -->|"--repo (Adopt-First)"| S3
```

---

## 2. Active Domain Packs Matrix

| Dimension | [`packs/gecx`](packs/gecx/README.md) (`v0.5.0`) | [`packs/adk`](packs/adk/README.md) (`v0.5.0`) | [`packs/generic`](packs/generic/README.md) (`v0.6.0`) | `packs/_template-pack` |
| :--- | :--- | :--- | :--- | :--- |
| **Status** | Active | Active | Active (`v0.6.0` `contrafile`) | Validated Starter Skeleton |
| **Target Platform** | CX Agent Studio (CES text + synthetic `BidiRunSession` audio) | ADK `2.15.0` (Dockerfile-first) + Gemini Enterprise (`GE App`) | Any software (Go, Node/TS, Python, Java, Rust, Web, CLI, Monorepo) | Template for new domains |
| **Offline Templates** | **16** (`gecx-*`, `<= 1,800` lines/role) | **16** (`adk-*`, `<= 1,800` lines/role) | **15** (`sw-*`, `<= 1,800` lines/role, filtered by `roster`) | **1** (`example-coordinator`) |
| **Hub Skill Bank** | **11** skills (5 project + 6 role-scoped) | **18** skills (5 project + 13 role-scoped incl. 7 `agents-cli`) | **10** skills (4 project + 6 role-scoped SEP/Kaizen) | `0` |
| **Pinned Toolchain** | `cxas-scrapi==1.11.0` + `/opt/gecx-foundry` | `google-adk[eval,a2a]==2.15.0` + `google-agents-cli==1.15.0` | Lean `core-gcp-fde-base` + `.factory/Dockerfile.customer` | `core-gcp-fde-base` |
| **Verification & Janitor** | CES `evaluationRuns` + `sandbox_janitor.py` | Vertex AI `reasoningEngines` + Discovery Engine `v1alpha` + `sandbox_janitor.py` | Profile-driven `generic_sandbox_gate.py` L1/L2 (`--base-ref`) + Cloud Run `sandbox_janitor.py` | Custom runner |
| **CI PR Gate & Tracker** | `gecx-verdict-gate.yml` (GitHub Issues/PRs) | `adk-verdict-gate.yml` (GitHub Issues/PRs) | `generic_sandbox_gate.py` + `kp-check` (GitHub Issues or `.factory/waves/wave-1.yaml` seed for ADO/GitLab/Git) | — |

---

## 3. Opinionated Vertex AI Model Routing (Generic Scion Tiers)

All packs default to **Vertex AI** (`auth_selected_type: vertex-ai`, zero static API keys, `global` endpoint with regional override) and route roles through Scion's **generic semantic tiers** (`small`, `medium`, `large`, `extra-large`) plus canonical `thinking_level` (`0–100`). Concrete model IDs evolve automatically as upstream Scion releases update their alias table, while any role may still pin an explicit Vertex AI model ID in `.factory/hub-project.yaml`.

| Diversity Profile | Default? | Builder / Architect | Code Reviewer / Security Auditor | Doc Writer | Model Garden Requirement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`cross-model`** | **Yes (Day-1 Safe)** | `antigravity-vertex` • `extra-large` (`100`) | `antigravity-vertex` • `large` (`100`) | `antigravity-vertex` • `medium` (`50`) | **1P Gemini only** (`claude_model_garden_enabled: false`) |
| **`cross-vendor`** | Opt-In | `antigravity-vertex` • `extra-large` (`100`) | `claude-vertex` • `large` (`75`) | `antigravity-vertex` • `medium` (`50`) | Requires manual Claude opt-in in Vertex AI Model Garden + `claude_model_garden_enabled: true` |
| **`single-family`** | Lab / Restricted | `antigravity-vertex` • `extra-large` (`100`) | Same family (mandatory human PR warning) | `antigravity-vertex` • `medium` (`50`) | 1P Gemini only |

> **Fail-Closed Opt-In:** `parse_hub_project.py` and `model_routing.py` reject `cross-vendor` or any `claude-vertex` role when `harnesses.claude_model_garden_enabled` is `false`.

---

## 4. End-to-End Lifecycle — From Day-0 Scan to Closed-Loop Kaizen

```mermaid
flowchart LR
    D0["Day-0 Brownfield Scan<br/>factory_onboard.py scan<br/>(0 tokens)"] --> GRILL["PO /grill-me Interview<br/>Express 10m or Complete 25m"]
    GRILL --> READY{"Readiness Gate<br/>check --json"}
    READY -->|"ready=false"| GRILL
    READY -->|"ready=true"| EMIT["Emit Layer 3 Overlay<br/>.factory/ + AGENTS.md block"]
    EMIT --> BOOT["Stage 03 Apply<br/>Harnesses + Templates + SAs<br/>+ weekly-kaizen cron"]
    BOOT --> BUILD["SEP Agent Team<br/>Investigate -> Design -> Code<br/>-> Blind Review -> Split-SA Sandbox"]
    BUILD --> PR["GitHub PR + Verdict Gate<br/>Live API Proof + always() Janitor"]
    PR -->|"Merge + Kaizen-Ref"| KZ["Weekly Closed-Loop Kaizen<br/>kaizen_collect.py + kaizen_verifier.py<br/>verified_pass / rollback_triggered"]
    KZ -.->|"Approved Hygiene PR"| BUILD
```

---

## 5. Quickstart (5 Steps)

```bash
# 1. Create Python 3.12 virtualenv and install catalog tooling
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"

# 2. Run static contract, SHA-40 lockfile, context budget, 90d TTL, and clean-room checks
./build.sh --check packs/gecx
./build.sh --check packs/adk
./build.sh --check packs/generic
./build.sh --check packs/_template-pack

# 3. Run the complete offline unit test suite
./build.sh --test

# 4. Build self-contained offline Release Kits (zero external URIs)
./build.sh --release-kit packs/gecx    --out /tmp/gecx-kit
./build.sh --release-kit packs/adk     --out /tmp/adk-kit
./build.sh --release-kit packs/generic --out /tmp/generic-kit

# 5. Scan an existing customer repository and emit a pre-filled draft profile (0 tokens)
.venv/bin/python core-gcp-fde/scripts/factory_onboard.py scan \
  --repo /path/to/customer-repo \
  --pack generic --track complete --emit-draft /tmp/profile-draft.yaml --json
```

---

## 6. Repository Navigation Index

| Area | Guide / Sub-README | What You Will Find |
| :--- | :--- | :--- |
| **Core Layer (Layer 1)** | [`core-gcp-fde/README.md`](core-gcp-fde/README.md) | 5 core skills, 6-pillar `/grill-me` bank, Vertex AI harness configs, Kaizen collector/verifier, Brownfield scanner & emitter |
| **GECX Pack (Layer 2)** | [`packs/gecx/README.md`](packs/gecx/README.md) | 16 `gecx-*` templates, 11 skills, `cxas 1.11.0`, split-SA CES Sandbox sequence, audio `BidiRunSession` |
| **ADK Pack (Layer 2)** | [`packs/adk/README.md`](packs/adk/README.md) | 16 `adk-*` templates, 18 skills (`agents-cli`), Dockerfile-first deploy, dual `GE App` export (`agent_engine` & `a2a`) |
| **Generic Pack (Layer 2)** | [`packs/generic/README.md`](packs/generic/README.md) | 15 `sw-*` SEP templates, 10 skills, lean `core-gcp-fde-base` image, profile-driven `generic_sandbox_gate.py`, non-GitHub `wave-1.yaml` queue |
| **3-Stage Deployment** | [`deploy/README.md`](deploy/README.md) | Stage 01 Terraform Landing Zone, Stage 02 `lite-vm` / `ha-gke` (Preview), Stage 03 image rebuild vs. mirror & Hub bootstrap |
| **JSON Contracts** | [`schemas/README.md`](schemas/README.md) | Producer-to-consumer contract map across all 8 JSON Schemas (`Draft 2020-12`) |
| **Drift Canaries** | [`canaries/README.md`](canaries/README.md) | Upstream CLI/API snapshot guards for `scion`, `cxas-scrapi`, and Discovery Engine `v1alpha` |
| **Operations Manual** | [`docs/AGENT_AUTHORING_AND_OPERATIONS.md`](docs/AGENT_AUTHORING_AND_OPERATIONS.md) | Comprehensive Scion `v0.4.0-preview.3+` & multi-pack (`gecx`, `adk`, `generic`) didactic guide: IAP Web UI, filesystem, Artifacts/Decisions, `/grill-me`, Knowledge Plane, Kaizen, HC-01–12 & Day-2 triage |
| **Landing Zone & Org Policies** | [`docs/CUSTOMER_LANDING_ZONE_REQUIREMENTS.md`](docs/CUSTOMER_LANDING_ZONE_REQUIREMENTS.md) | 3/2/1-project & optional no-Sandbox topologies, APIs, Split-SA isolation (`vertexInferencePredict`, `adk_runtime`, `generic`), Org Policy matrix & FinOps guardrails |
| **Hands-On Walkthrough** | [`docs/HANDS_ON_WALKTHROUGH.md`](docs/HANDS_ON_WALKTHROUGH.md) | Step-by-step zero-to-teardown walkthrough across `gecx`, `adk`, and `generic` paired with `./scripts/hands-on-walkthrough.sh` |
| **Formal Kaizen & Brownfield Spec** | [`docs/specs/SPEC_KAIZEN_AND_BROWNFIELD_ONBOARDING.md`](docs/specs/SPEC_KAIZEN_AND_BROWNFIELD_ONBOARDING.md) | Formal ASD-STE100 baseline specification for `v0.3.0` + `v0.4.0` (extended by `ADR-014`–`ADR-016` for `v0.5.0`/`v0.6.0`) |
| **Architecture Decision Records** | [`docs/adr/README.md`](docs/adr/README.md) | Formal traceable ADRs (`ADR-001`–`ADR-016`) governing boundaries, IAM, Vertex AI, native ADK, cognitive onboarding, and `packs/generic` |
| **Architectural Invariants** | [`docs/INVARIANTS.md`](docs/INVARIANTS.md) | 18 enforceable invariants (`INV-01`–`INV-18`) traced to `ADR-001`–`ADR-016`, code paths, and automated tests |
| **Hillclimbing Charter** | [`docs/HILLCLIMBING_CHARTER.md`](docs/HILLCLIMBING_CHARTER.md) | Functional-first live GCP qualification program (`HC-01`–`HC-12`, VM+GECX, GKE+ADK, Generic no-Sandbox, 5-repo shared Hub, `INV-18` Zero-Silent-403, `$0` teardown proof) |
