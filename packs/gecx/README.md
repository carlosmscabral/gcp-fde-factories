# `packs/gecx` — CX Agent Studio Autonomous Factory Pack (`v0.5.0`)

Reusable autonomous software factory pack for **Google Cloud Customer Engagement Suite (CES) / CX Agent Studio (GECX)** supporting text, callback unit tests, golden/simulation evaluations, and synthetic `BidiRunSession` audio verification.

---

## 1. Architecture & 16-Role SEP Hierarchy

`packs/gecx` composes all 13 upstream roles from `scion-frontiers/agent-team@08faf48` (read-only Layer 0) with 3 domain/operations specialists (`gecx-deployer`, `gecx-eval-tester`, `gecx-kaizen-analyst`). Every role stays under the **1,800-line context budget** enforced by `./build.sh --check packs/gecx`.

```mermaid
flowchart TD
    Human(["Customer Principal / PO"]) -->|"--task-file"| Coord["gecx-coordinator<br/>role: full • SA: factory-worker"]
    Coord -->|"Depth-3"| EM["gecx-eng-manager<br/>role: full • SA: factory-worker"]

    subgraph DISCOVERY["Discovery & Design (baseline • factory-worker)"]
        Inv["gecx-investigator"]
        Arch["gecx-architect"]
        Res["gecx-researcher"]
    end

    subgraph BUILD["Build, Review & Security (baseline • factory-worker)"]
        Dev["gecx-developer"]
        Rev["gecx-code-reviewer<br/>Blind cross-model/vendor"]
        Test["gecx-test-engineer"]
        Sec["gecx-security-auditor"]
        Support["qa-tester • doc-writer<br/>release-notes • web-builder"]
    end

    subgraph SANDBOX["Split-SA Sandbox Verification (baseline)"]
        Dep["gecx-deployer<br/>SA: gecx-deployer<br/>Role: gecxSandboxDeployer"]
        Eval["gecx-eval-tester<br/>SA: gecx-evaluator<br/>Role: gecxSandboxEvaluator"]
    end

    subgraph KAIZEN["Closed-Loop Kaizen (weekly-kaizen --wake)"]
        KZ["gecx-kaizen-analyst<br/>role: baseline • SA: factory-worker"]
    end

    Coord --> Inv
    Coord --> Arch
    Coord --> Res
    Coord --> KZ
    EM --> Dev
    EM --> Rev
    EM --> Test
    EM --> Sec
    EM --> Support
    EM --> Dep
    EM --> Eval
    Dep -->|"App resource name"| Eval
    Eval -->|"Contract 5 Verdict JSON"| Human
```

---

## 2. Split-SA Verification Sequence (Zero-PII Anti-Forgery)

Every PR touching `cxas_app/` runs two strictly separated Service Accounts in the disposable Sandbox project. Neither SA inherits the 79 `contactcenterinsights.*` or `ces.conversations.*` permissions present in predefined `roles/ces.*`.

```mermaid
sequenceDiagram
    autonumber
    participant Runner as gecx-eval-runner.sh
    participant Dep as gecx-deployer SA
    participant Eval as gecx-evaluator SA
    participant CES as CES Sandbox API
    participant CI as gecx-verdict-gate.yml
    participant Jan as gecx-janitor SA

    Runner->>Runner: Level 1 offline lint + sync-callbacks + test-callbacks
    Runner->>Dep: cxas push + push-eval (PR-N-sha7)
    Dep->>CES: Import ephemeral [CI] PR-N-sha7 app
    CES-->>Dep: Return app resource name
    Runner->>Eval: Run cxas test-tools and cxas run eval-type all wait
    Eval->>CES: Execute tool tests, goldens, and synthetic audio
    Eval->>CES: GET /v1beta/app/evaluationRuns
    CES-->>Eval: Confirm totalCount > 0 and failedCount == 0
    Eval-->>Runner: Write validated .factory/verdicts/pr-N.json
    CI->>CES: Independent GET app + evaluationRuns (inside pinned image)
    CES-->>CI: Confirm [CI] PR-N-sha7 binding & initiatedBy == Evaluator SA
    CI->>Jan: if: always() DELETE ?force=true
    Jan->>CES: Delete ephemeral [CI] app
```

---

## 3. Hub Skill Bank Breakdown (11 Skills)

| Attachment Scope | Skills | Purpose |
| :--- | :--- | :--- |
| **Project-Attached (5)** | `gcp-fde-guardrails`, `gcp-sandbox-contract`, `gcp-kaizen-light`, `gecx-foundry-adapter`, `gecx-domain-guardrails` | Mounted on every role via `scion project skills add` (core rules, 6-level Verdict ladder, `cxas 1.11.0` guardrails, `/opt/gecx-foundry` adapter) |
| **Role-Scoped (6)** | `software-engineering-process`, `code-review`, `artifact-durability`, `agent-state-continuity`, `release-notes-daily`, `gcp-kaizen-analyst` | Mounted via `skill://scion/global/<name>` strictly on roles that need them, keeping `gecx-deployer` and `gecx-eval-tester` lean |

---

## 4. Honest Sandbox Boundary (`not-verifiable-in-sandbox`)

The GECX Sandbox verifies **text flows**, **offline Python callbacks**, **tool unit tests**, **golden/simulation evals**, and **synthetic `BidiRunSession` audio**. Changes touching **SIP trunks, SBCs, AudioCodes VAIC, carrier 8 kHz audio, DTMF, or live CCaaS transfers** must emit `not-verifiable-in-sandbox` with explicit `not_verifiable_surfaces` for human sign-off.

---

## 5. Key Commands

```bash
# Validate pack schema, SHA-40 lockfile, 1,800-line budgets, TTLs, and clean-room rules
./build.sh --check packs/gecx

# Build self-contained offline Release Kit
./build.sh --release-kit packs/gecx --out /tmp/gecx-kit

# Verify cxas-scrapi 1.11.0 CLI contract canary
.venv/bin/python canaries/gecx/check_cli_contract.py

# Run Level 1 offline checks on the starter scaffold
.venv/bin/python packs/gecx/scripts/gecx_sandbox_gate.py \
  --repo-dir packs/gecx/repo-scaffold \
  --app-dir cxas_app/Starter_App \
  --pr-number 1 \
  --commit-sha 0123456789abcdef0123456789abcdef01234567 \
  --mode level1-only \
  --verdict-out /tmp/gecx-l1-verdict.json
```
