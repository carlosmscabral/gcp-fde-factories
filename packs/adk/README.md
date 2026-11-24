# `packs/adk` — ADK 2.15 + Dockerfile-First + Gemini Enterprise App Factory Pack (`v0.1.0`)

Reusable autonomous software factory pack for **Google Cloud Agent Development Kit (`google-adk[eval,a2a]==2.15.0`)** built around an opinionated **container-first root `Dockerfile`** deployment contract (`agents-cli deploy`), **7 vendored upstream `google/agents-cli v1.15.0` skills**, and deterministic dual export into **Gemini Enterprise (`GE App`)**.

---

## 1. Deployment & Dual Gemini Enterprise (`GE App`) Export Topology

Every ADK agent repository ships a root `Dockerfile` running `adk api_server` under a non-root user so the exact same container builds and deploys consistently across **Vertex AI Agent Engine Runtime**, **Cloud Run**, and **GKE**, then exports cleanly to **Gemini Enterprise** via Discovery Engine `v1alpha`.

```mermaid
flowchart LR
    subgraph REPO["Customer ADK Repository"]
        PKG["agent/ (Modular <=250L root)<br/>agent.py • config.py • prompts.py • tools.py"]
        DF["Root Dockerfile<br/>non-root USER + adk api_server"]
        MAN["ge_manifest.json<br/>(schemas/ge-export.schema.json)"]
        EVALS["evals/synthetic/*.evalset.json<br/>+ tests/test_*.py"]
    end

    subgraph L1["Level 1 Offline Gate (0 Credentials)"]
        PYT["pytest tests/"]
        DFCHK["Final-stage Dockerfile Contract"]
        GEEXP["ge_export.py validate & export"]
    end

    subgraph TARGETS["Container Runtime Targets (agents-cli deploy)"]
        AE["Vertex AI Agent Engine<br/>(agent_runtime)"]
        CR["Cloud Run / GKE<br/>(A2A /.well-known/agent-card.json)"]
    end

    subgraph GE["Gemini Enterprise (Discovery Engine v1alpha)"]
        GE_AE["export_mode: agent_engine<br/>adkAgentDefinition.provisionedReasoningEngine<br/>+ toolAuthorizations"]
        GE_A2A["export_mode: a2a<br/>a2aAgentDefinition.jsonAgentCard (A2A v0.3.0)<br/>+ agentAuthorization"]
    end

    PKG --> PYT
    DF --> DFCHK
    MAN --> GEEXP
    EVALS --> PYT
    PYT --> AE
    DFCHK --> AE
    DFCHK --> CR
    GEEXP -->|"POST or PATCH reuse"| GE_AE
    GEEXP -->|"A2A AgentCard"| GE_A2A
    AE --> GE_AE
    CR --> GE_A2A
```

---

## 2. Split-SA Anti-Forgery Sequence & Dual Janitor

```mermaid
sequenceDiagram
    autonumber
    participant Gate as adk_sandbox_gate.py
    participant Dep as adk-deployer SA
    participant Eval as adk-evaluator SA
    participant GCP as Vertex AI & Discovery Engine
    participant CI as adk-verdict-gate.yml
    participant Jan as adk-janitor SA

    Gate->>Gate: Level 1 scrubbed env (pytest, Dockerfile, ge_export)
    Gate->>Dep: Phase A deploy (POST or PATCH sandbox GE agent)
    Dep->>GCP: Register [CI] PR-N-sha7 GE agent & write state handoff
    GCP-->>Dep: Return ge_agent_resource
    Gate->>Eval: Phase B evaluate (scrubbed env, CLOUDSDK_AUTH_ACCESS_TOKEN)
    Eval->>GCP: Run adk eval (sandboxEvaluatorPredict only)
    GCP-->>Eval: Tests passed > 0 and failed == 0
    Eval-->>Gate: Write validated .factory/verdicts/pr-N.json
    CI->>GCP: Independent GET reasoningEngine + GE agent (pinned image)
    GCP-->>CI: Verify [CI] PR-N-sha7 binding and ACTIVE state
    CI->>Jan: if: always() DELETE ephemeral engine & non-reused GE agent
```

---

## 3. Roles & Hub Skill Bank Breakdown (16 Templates, 18 Skills)

| Category | Count | Included Items | Context Strategy |
| :--- | :--- | :--- | :--- |
| **Templates (`adk-*`)** | **16** | 13 SEP roles (`scion-frontiers/agent-team@08faf48`) + `adk-deployer` + `adk-eval-tester` + `adk-kaizen-analyst` | All 16 roles strictly `<= 1,800` lines |
| **Project-Attached Skills** | **5** | `gcp-fde-guardrails`, `gcp-sandbox-contract`, `gcp-kaizen-light`, `adk-domain-guardrails`, `ge-app-export` | Attached to every role via `scion project skills add` |
| **SEP & Kaizen Role Skills** | **6** | `software-engineering-process`, `code-review`, `artifact-durability`, `agent-state-continuity`, `release-notes-daily`, `gcp-kaizen-analyst` | Role-scoped via `skill://scion/global/<name>` |
| **Vendored `google/agents-cli` Skills** | **7** | `google-agents-cli-workflow`, `scaffold`, `adk-code`, `eval`, `deploy`, `publish`, `observability` (Apache-2.0 @ `2fa159a8`) | Role-scoped strictly to matching roles (`architect`, `developer`, `test-engineer`, `adk-deployer`, `adk-eval-tester`) |

---

## 4. Key Commands

```bash
# 1. Validate pack schema, lockfile, budgets, and clean-room rules
./build.sh --check packs/adk

# 2. Build self-contained offline Release Kit
./build.sh --release-kit packs/adk --out /tmp/adk-kit

# 3. Validate and export a Gemini Enterprise registration bundle
.venv/bin/python packs/adk/scripts/ge_export.py export \
  --manifest packs/adk/repo-scaffold/ge_manifest.json \
  --out /tmp/ge-export

# 4. Run Level 1 offline verification (pytest + Dockerfile contract + GE bundle)
.venv/bin/python packs/adk/scripts/adk_sandbox_gate.py \
  --repo-dir packs/adk/repo-scaffold \
  --pr-number 1 \
  --commit-sha 0123456789abcdef0123456789abcdef01234567 \
  --mode level1-only \
  --verdict-out /tmp/adk-l1-verdict.json

# 5. Run Discovery Engine v1alpha + A2A v0.3.0 contract canary
.venv/bin/python canaries/adk/check_ge_contract.py
```
