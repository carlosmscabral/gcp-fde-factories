# Requisitos de Landing Zone para Clientes — Fábricas GCP FDE (`packs/gecx`, `packs/adk` e `packs/generic`)

**Versão:** `v0.6.0` (Release `contra-filé` — 26/11/2026 BRT)
**Audiência:** Times de Plataforma GCP, SecOps, IAM, FinOps e Engenharia de IA do Cliente
**Escopo:** Piloto e operação controlada de fábricas autônomas **GECX (`packs/gecx`)**, **ADK + Gemini Enterprise (`packs/adk`)** e **Software Genérico (`packs/generic`, `sw-*`)** dentro do Google Cloud do cliente

---

## 1. Visão Geral e Separação de Responsabilidades

A fábrica roda integralmente dentro da organização Google Cloud do cliente. Nenhum código de produção, conversa real ou dado pessoal (PII) sai do perímetro do cliente.

```mermaid
flowchart LR
    P1["Estágio 01: Landing Zone<br/>(Plataforma / SecOps)<br/>VPC, AR, 4-10 SAs, Custom Roles, WIF"] -->|"landing-zone-outputs.json"| P2["Estágio 02: Factory Runtime<br/>(lite-vm Shielded ou ha-gke Bridge)"]
    P2 -->|"Hub saudável via IAP"| P3["Estágio 03: Hub Bootstrap<br/>(Principal do Cliente + FDE)<br/>stage-release-kit -> apply"]
    P3 -->|"PR + Veredito verificado"| CI["GitHub Actions do Cliente<br/>(WIF -> Verdict Gate -> DEV/HML/PRD)"]
```

| Estágio | Executor Recomendado | O que Provisiona | Privilégio Necessário |
| :--- | :--- | :--- | :--- |
| **01 — `01-landing-zone`** | Plataforma / SecOps do Cliente | Rede (VPC nova ou Shared VPC), Artifact Registry, **4 a 10 SAs** (7 base com Sandbox + até 3 opcionais: `gke-node`, `adk-runtime`, `kaizen`; 4 quando `enable_sandbox_project=false`), **Custom Roles explícitas sem curingas**, opcional GitHub WIF (requer Sandbox ativo), bucket efêmero e Budget Alert + tópico Pub/Sub. | `Owner` temporário nos projetos alvo (ou `Project IAM Admin` + `Service Account Admin` + `Role Administrator` + `Service Usage Admin` + `Compute Network Admin` + `Artifact Registry Admin` + `Storage Admin` + `Pub/Sub Admin` + `Workload Identity Pool Admin`) + `Billing Budgets Admin` na conta de faturamento |
| **02 — `02-factory-runtime`** | Plataforma ou FDE | Perfil **`lite-vm`** (Shielded VM sem IP público, SHA-256 pinado do binário Scion) **ou** **`ha-gke`** *(Validated Contract Bridge com 0 recursos TF — valida inputs e emite parâmetros para o módulo Terraform/Helm upstream do Scion)*. | Compute Admin (sem IAM Admin) |
| **03 — `03-hub-bootstrap`** | **Principal do Cliente** (+ FDE) | Rebuild/espelhamento de imagens por `@sha256:`, configurações do Scion Hub, registro de SAs, skills, harness-configs Vertex AI globais, templates filtrados por `roster`, agenda `weekly-kaizen` e start do `<prefix>-coordinator` sob posse do cliente. | Hub Admin + `roles/iam.serviceAccountUser` nas SAs atribuíveis + `cloudbuild.builds.editor` (modo `rebuild`) |

> [!IMPORTANT]
> **Posse obrigatória no Dia 1:** Um **principal do cliente** (nunca um FDE temporário) deve iniciar o agente raiz (`<prefix>-coordinator`). Quando o criador perde acesso ao projeto, o Scion restringe os agentes dele na varredura de standing.

---

## 2. Topologia de Projetos Suportada (Mesmo Código Terraform)

```mermaid
flowchart TB
    subgraph HUB["Hub Project (hub_project_id)"]
        VM["Scion Hub Runtime<br/>(SA: prefix-hub)"]
        AR["Artifact Registry<br/>factory-images"]
        CB["Cloud Build Rebuild<br/>(SA: prefix-builder)"]
    end

    subgraph INF["Inference Project (inference_project_id)"]
        VTX["Vertex AI Models<br/>(SA: prefix-worker)<br/>TPM Quotas + Budget Kill-Switch"]
        KZ["Opcional: prefix-kaizen<br/>(Monitoring/Logging Viewer)"]
    end

    subgraph SBX["Disposable Sandbox Project (sandbox_project_id)"]
        DEP["Deployer SA (prefix-deployer)<br/>gecxSandboxDeployer / adkSandboxDeployer"]
        EVL["Evaluator SA (prefix-eval)<br/>gecxSandboxEvaluator / adkSandboxEvaluator<br/>+ sandboxEvaluatorPredict"]
        JAN["Janitor SA (prefix-janitor)<br/>NUNCA no Hub (CI / Cloud Scheduler)"]
    end

    VM -->|"Impersonação curta (0 JSON keys)"| VTX
    VM -->|"Impersonação (modo sandbox-direct)"| DEP
    VM -->|"Impersonação (modo sandbox-direct)"| EVL
    CB -->|"Push @sha256"| AR
    EVL -.->|"Pull imagem CI (WIF)"| AR
```

O módulo [deploy/01-landing-zone](../deploy/01-landing-zone) aceita `hub_project_id`, `inference_project_id`, `sandbox_project_id` e `enable_sandbox_project` (padrão `true`), suportando quatro topologias sem alteração de código:

![Landing Zone GCP, Topologias Flexíveis & Isolamento Split-SA Zero-PII](assets/gcp_landing_zone_and_split_sa.png)

| Topologia | Recomendado Para | Isolamento Obtido |
| :--- | :--- | :--- |
| **3 Projetos (Padrão Produção)** | Pilotos corporativos e produção | Hub/AR isolados, faturamento e cotas TPM de Vertex AI em Projeto de Inferência dedicado, apps e agentes `[CI]` em Sandbox descartável. |
| **2 Projetos (Piloto Ágil)** | Pilotos rápidos | `hub_project_id == inference_project_id` + `sandbox_project_id` descartável separado. |
| **2 ou 1 Projeto Sem Sandbox (Exceção CI-Only)** | `enable_sandbox_project = false` (`mode: ci-only` ou `deploy_target: none`) | Omite SAs/roles de Sandbox e roteia o bucket de staging do Cloud Build para `hub_project_id` (qualificado em `HC-08`). |
| **1 Projeto Com Sandbox (Restrito)** | Laboratório ou `disableCrossProjectServiceAccountUsage` | Todas as variáveis apontam para o mesmo projeto, mantendo separação lógica por SA e Custom Roles. |

Ambientes superiores (**DEV / HML / PRD**) **nunca** recebem Service Accounts registradas no Scion Hub. Promoções ocorrem exclusivamente pelo CI/CD do cliente após aprovação humana obrigatória no Pull Request.

---

## 3. APIs Google Cloud Obrigatórias por Projeto

| Projeto Alvo | APIs Obrigatórias | Motivo Técnico |
| :--- | :--- | :--- |
| **Hub (`hub_project_id`)** | `compute`, `oslogin`, `run`, `iap`, `artifactregistry`, `secretmanager`, `cloudbuild`, `storage`, `pubsub`, `billingbudgets`, `iam`, `policytroubleshooter`, `cloudresourcemanager`, `iamcredentials`, `logging`, `monitoring` *(+ `container` se `enable_gke_api=true`)* — fonte única: `deploy/01-landing-zone/apis.tf` | VM/GKE, IAP SSH (`oslogin` é obrigatório com `enable-oslogin=TRUE`), `policytroubleshooter` (obrigatório em `gcp_iam_check_mode=enforce`), Artifact Registry, Cloud Build + staging bucket fallback e alertas FinOps. |
| **Inferência (`inference_project_id`)** | `aiplatform`, `serviceusage`, `logging`, `monitoring`, `billingbudgets` | Chamadas Vertex AI (Gemini 1P e Claude opt-in no Model Garden), cotas TPM e orçamento dedicado. |
| **Sandbox (`sandbox_project_id`, se `enable_sandbox_project=true`)** | **Base:** `aiplatform`, `storage`, `serviceusage`, `iamcredentials`, `logging` • **Se `enable_gecx_sandbox_roles=true`:** `ces`, `texttospeech` • **Se `enable_adk_sandbox_roles=true`:** `discoveryengine`, `run`, `cloudbuild` • **Se `enable_generic_sandbox_roles=true`:** `run`, `cloudbuild` | Apps efêmeros CES (`[CI]`), áudio sintético (`BidiRunSession`), Vertex AI Agent Engine (`reasoningEngines`), registro Gemini Enterprise (`discoveryengine`), serviços efêmeros Cloud Run (`[CI]`) e bucket efêmero (TTL 1 dia). |

---

## 4. Identidade, IAM e Isolamento Zero-PII (Zero Chaves JSON)

A arquitetura proíbe chaves estáticas JSON de Service Account. O Scion Hub emite tokens curtos via impersonação (`roles/iam.serviceAccountTokenCreator`) com `gcp_iam_check_mode: enforce`, `default_gcp_identity_mode: block`, `default_agent_role: baseline` (em `settings.yaml`) e `gcp_iam_deny_unknown_policy: fail-open` para Hub SAs com escopo de projeto (ou `fail-closed` quando a organização concede `roles/iam.denyReviewer` — defina de forma coerente tanto a var TF `gcp_iam_deny_unknown_policy` no Stage 02 quanto `GCP_IAM_DENY_UNKNOWN_POLICY` em todo `apply` do Stage 03, `INV-14`).

### 4.1 Custom Roles Explícitas Sem Curingas (Inferência e Sandbox)

1. **Por que os 11 papéis pré-definidos `roles/ces.*` são proibidos:** todos herdam **79 permissões de `contactcenterinsights.*` e `ces.conversations.*`** (violando zero-PII), enquanto `roles/ces.appEditor` omite `ces.agents.*`, `ces.tools.*`, `ces.toolsets.*` e `ces.guardrails.*`.
2. **Por que `roles/aiplatform.user` é proibido em `worker` e `evaluator` (`INV-03`):** ele permite criar/mutar `reasoningEngines`. Substituímos pelas Custom Roles explícitas **`vertexInferencePredict`** (no `inference_project_id`) e **`sandboxEvaluatorPredict`** (no `sandbox_project_id`), contendo exclusivamente `aiplatform.endpoints.predict`.
3. **Atenção ao default de `enable_gecx_sandbox_roles`:** em `variables.tf`, `enable_gecx_sandbox_roles` vem `true` por padrão. Para `packs/adk` ou `packs/generic`, passe explicitamente **`enable_gecx_sandbox_roles = false`** para não conceder 65 permissões CES desnecessárias.

| Custom Role | Projeto & Gatilho | Permissões Explícitas | Finalidade |
| :--- | :--- | :--- | :--- |
| **`vertexInferencePredict`** | `inference_project_id` (sempre) | `aiplatform.endpoints.predict` (1 perm) | Permite inferência Vertex AI para `worker`, `deployer`, `eval`, `kaizen` e `adk-runtime` sem poder criar `reasoningEngines` (`INV-03`). |
| **`sandboxEvaluatorPredict`** | `sandbox_project_id` (`enable_sandbox_project=true`) | `aiplatform.endpoints.predict` (1 perm) | Permite predição de modelos na avaliação no Sandbox sem poder criar ou alterar `reasoningEngines`. |
| **`gecxSandboxDeployer`** | Sandbox (`enable_gecx_sandbox_roles=true`) | **65** perms explícitas de metadados + escrita CES (`iam.tf:124`) | Cria, importa, atualiza e remove apps `[CI]` no Sandbox (zero conversas/Insights). |
| **`gecxSandboxEvaluator`** | Sandbox (`enable_gecx_sandbox_roles=true`) | **38** perms explícitas de leitura + `runEvaluation` + `bidiRunSession` (`iam.tf:136`) | Roda avaliações e áudio sintético; retorna HTTP 403 em escrita de app e `ces.conversations.list`. |
| **`gecxSandboxJanitor`** | Sandbox (`enable_gecx_sandbox_roles=true`) | **7** perms explícitas (`apps.list/get/delete`, `locations`, `operations`) | Limpa apps `[CI]` expirados (`> 4h`). |
| **`adkSandboxDeployer`** | Sandbox (`enable_adk_sandbox_roles=true`) | **23** perms explícitas (`aiplatform.reasoningEngines.*`, `discoveryengine.agents.*`, Cloud Run/Build — `iam.tf:548-572`) | Implanta `reasoningEngines` / Cloud Run e registra agentes `[CI]` no Gemini Enterprise Sandbox. |
| **`adkSandboxEvaluator`** | Sandbox (`enable_adk_sandbox_roles=true`) | **5** perms somente leitura/execução (`reasoningEngines.get/list/query`, `discoveryengine.agents.get/list`, `run.routes.invoke`) | Executa `adk eval`, smoke A2A e leitura independente de proveniência no CI sem mutar recursos. |
| **`adkSandboxJanitor`** | Sandbox (`enable_adk_sandbox_roles=true`) | **6** perms explícitas de listagem e deleção (`reasoningEngines`, `discoveryengine.agents`, `run.services`) | Varre e remove `reasoningEngines`, agentes GE `[CI]` e serviços Cloud Run órfãos (`factory_ci=true`, `HC-06`). |
| **`genericSandboxDeployer`** | Sandbox (`enable_generic_sandbox_roles=true`) | **11** perms (`cloudbuild.builds.*`, `run.services.*`, `run.revisions.*`, `run.operations.get`) | Compila e implanta serviços Cloud Run `[CI]` para `packs/generic` sem permissões ADK/CES (`ADR-016`). |
| **`genericSandboxEvaluator`** | Sandbox (`enable_generic_sandbox_roles=true`) | **3** perms (`run.routes.invoke`, `run.services.get/list`) | Invoca e valida serviços efêmeros Cloud Run sem escrita. |
| **`genericSandboxJanitor`** | Sandbox (`enable_generic_sandbox_roles=true`) | **3** perms (`run.services.list/get/delete`) | Remove serviços Cloud Run `[CI]` expirados. |

### 4.2 Matriz Completa de Service Accounts (4 a 10 SAs conforme Toggles)

| Service Account | Projeto | Registrada no Hub? | Permissões Mínimas |
| :--- | :--- | :--- | :--- |
| `<prefix>-hub@` | Hub | Runtime do Hub | `roles/iam.securityReviewer` nos projetos alvo + `roles/iam.serviceAccountTokenCreator` apenas nas SAs atribuíveis (`worker`, e se ativos: `deployer`, `eval`, `kaizen`) + `artifactregistry.reader` + `logging.logWriter`. |
| `<prefix>-iap@` | Hub | Não (Proxy IAP) | Zero roles de projeto (invocação interna do backend apenas). |
| `<prefix>-builder@` | Hub | Não (Cloud Build) | `artifactregistry.writer`, `logging.logWriter`, `storage.objectViewer` (usada no `--mode rebuild`). |
| `<prefix>-gke-node@` *(se `enable_gke_api=true`)* | Hub | Não (Nós GKE) | Identidade dedicada de nós GKE (`ADR-013`). |
| `<prefix>-worker@` | Inferência | **Sim (Label: `factory-worker`)** | **`vertexInferencePredict`** (nunca `roles/aiplatform.user`), `serviceusage.serviceUsageConsumer`, `logging.logWriter`, `monitoring.metricWriter`. |
| `<prefix>-deployer@` *(se Sandbox ativo)* | Sandbox | **Sim** (`sandbox-direct`) | Custom Role Deployer do pack + `vertexInferencePredict` na Inferência + `serviceusage.serviceUsageConsumer` + `storage.objectAdmin` / `storage.bucketViewer` no bucket de staging + `artifactregistry.reader` no Hub; em ADK/Generic também recebe `cloudbuild.builds.editor` + `serviceUsageConsumer` no Hub, e `iam.serviceAccountUser` em `builder`, `adk-runtime` e `worker` (em ADK). |
| `<prefix>-eval@` *(se Sandbox ativo)* | Sandbox | **Sim** (`sandbox-direct`) | Custom Role Evaluator do pack + **`sandboxEvaluatorPredict`** + `vertexInferencePredict` na Inferência + `serviceusage.serviceUsageConsumer` + `storage.objectViewer` + **`artifactregistry.reader` no Hub**. |
| `<prefix>-adk-runtime@` *(se `enable_adk_sandbox_roles=true`)* | Sandbox | Não (Runtime ADK) | Same-project SA (`ADR-013`): `vertexInferencePredict` + `serviceUsageConsumer` na Inferência e `artifactregistry.reader` no Hub; **zero escrita** no Sandbox. |
| `<prefix>-janitor@` *(se Sandbox ativo)* | Sandbox | **NUNCA** | Custom Role Janitor do pack + `serviceusage.serviceUsageConsumer` (usada apenas via WIF no CI `if: always()` e por Cloud Scheduler). |
| `<prefix>-kaizen@` *(se `enable_kaizen_gcp_obs=true`)* | Inferência | **Sim** *(se `kaizen.enable_gcp_obs: true`)* | `roles/monitoring.viewer` (Inferência) + `roles/logging.viewer` (Sandbox se ativo) + `vertexInferencePredict` + `serviceUsageConsumer` (`HC-04 F5`). |
| `service-<SBX_NUM>@gcp-sa-ces...` | Sandbox | Nativa GCP (`enable_gecx_sandbox_roles=true`) | `roles/storage.objectUser` no bucket efêmero de staging (evita falha no `cxas push`). |

- **Operadores Humanos (`var.factory_operator_members`):** recebem `roles/iam.serviceAccountUser` nas SAs atribuíveis e na `<prefix>-builder@`, além de `roles/cloudbuild.builds.editor` no Hub para rodar `stage-release-kit.sh --mode rebuild` sem precisar de Editor/Owner.
- **GitHub Actions WIF (`var.enable_github_wif = true` + `var.github_repository = "org/repo"`):** provisiona pool + provider OIDC restrito por `assertion.repository == var.github_repository` com `roles/iam.workloadIdentityUser` apenas em `<prefix>-eval@` e `<prefix>-janitor@`. **Requer `enable_sandbox_project = true`** (`iam.tf:801` omite o pool quando o Sandbox está desligado).
- **Jobs agendados fora do Hub:** o Stage 01 provisiona as SAs e permissões, enquanto o agendamento horário do Janitor (`packs/gecx/scripts/sandbox_janitor.py`, `packs/adk/scripts/sandbox_janitor.py`, `packs/generic/scripts/sandbox_janitor.py`) fica sob Cloud Scheduler / CI do operador. O Delta Watcher em `scripts/delta-watcher/watcher.py` é um protótipo offline (deploy nativo Cloud Run rastreado na Issue `#2`).

---

## 5. Rede, Acesso, Entrega de Imagens, GitHub e Modelos Vertex AI

1. **Rede sem VPC `default`:** Stage 01 cria VPC customizada + Private Google Access + Cloud NAT ou conecta a uma **Shared VPC** existente (`create_custom_vpc = false`). A VM `lite-vm` é Shielded e possui **zero IP público**.
2. **Acesso de Controle (IAP):** acesso administrativo exclusivamente via IAP TCP forwarding (`35.235.240.0/20`, porta 22) no perfil `lite-vm`, ou proxy HTTPS protegido por IAP restrito à organização do cliente.
3. **Entrega Híbrida do Release Kit (`stage-release-kit.sh`):**
   - **Modo `rebuild` (padrão — SecOps / Binary Authorization):** reconstrói a imagem lean de CI (`<pack>-runtime`) e, quando `--antigravity-base-image` / `--claude-base-image` são informados, reconstrói também as imagens completas de agente Scion com `sciontool` e carimba os `@sha256:` reais no `manifest.json` e nos `harness-configs/*/config.yaml`.
   - **Modo `mirror`:** espelha imagens já construídas por `@sha256:` via `crane`/`gcrane` (recusa placeholders `REPLACE_` ou digests zerados).
4. **GitHub (Pré-Requisito da v1):** proteção de branch em `main` (aprovação humana obrigatória, zero auto-merge), labels `eval-change-approved` e `no-verdict-approved` (para PRs docs-only), e variáveis de repositório (`GCP_WIF_PROVIDER`, `<PACK>_RUNTIME_IMAGE_DIGEST`, `<PACK>_SANDBOX_PROJECT_ID`, `<PACK>_EVALUATOR_SA_EMAIL`, `<PACK>_JANITOR_SA_EMAIL`).
5. **Modelos Ativos na Vertex AI (Padrão Vertex-First + Tiers Genéricos + Opt-In Manual de Claude):**
   - Por padrão, os scaffolds iniciam com **`diversity_profile: cross-model`** e **`harnesses.claude_model_garden_enabled: false`** (100% Vertex AI Gemini 1P usando tiers genéricos Scion `extra-large`, `large` e `medium`, com `GOOGLE_CLOUD_LOCATION=global`), garantindo funcionamento imediato no Dia 1 sem dependência de termos de terceiros.
   - Para ativar revisão **`cross-vendor`** com Anthropic Claude via Vertex AI (`claude-vertex`, `CLOUD_ML_REGION=global`), o cliente aceita manualmente os termos do modelo no **Vertex AI Model Garden** no `inference_project_id` e define `harnesses.claude_model_garden_enabled: true`. O bootstrap falha fechado caso `cross-vendor` ou `claude-vertex` seja solicitado com o opt-in desligado.

---

## 6. Organization Policies (`constraints/*`) e Controles de Perímetro (VPC-SC)

> [!NOTE]
> Esta matriz cobre os principais bloqueios Enterprise observados em Landing Zones Google Cloud, mas não é exaustiva. Execute o comando read-only da Seção 6.3 no Dia 0 antes de rodar o Terraform.

### 6.1 Org Policies Já Compatíveis por Design (Zero Exceção Necessária)

| Constraint | Status na Fábrica | Como a Arquitetura Atende |
| :--- | :--- | :--- |
| `constraints/iam.disableServiceAccountKeyCreation` / `disableServiceAccountKeyUpload` | **100% Compatível** | Zero chaves JSON estáticas (apenas tokens curtos via impersonação e WIF). |
| `constraints/compute.vmExternalIpAccess` | **100% Compatível** | VM `lite-vm` sem IP externo (`access_config` omitido); egress via Cloud NAT. |
| `constraints/compute.requireShieldedVm` | **100% Compatível** | Secure Boot, vTPM e Integrity Monitoring ativos na `lite-vm`. |
| `constraints/compute.requireOsLogin` | **100% Compatível** | `enable-oslogin=TRUE` e `oslogin.googleapis.com` habilitada no Stage 01. |
| `constraints/compute.skipDefaultNetworkCreation` | **100% Compatível** | Stage 01 nunca usa VPC `default` (VPC customizada ou Shared VPC). |
| `constraints/storage.uniformBucketLevelAccess` e `publicAccessPrevention` | **100% Compatível** | Bucket efêmero do Sandbox usa Uniform Bucket-Level Access e acesso privado. |
| `constraints/cloudbuild.disableCreateDefaultServiceAccount` e `useComputeServiceAccount` | **100% Compatível** | Stage 01 provisiona `<prefix>-builder@` dedicada. |
| `constraints/run.managed.requireInvokerIam` e `allowedIngress` | **100% Compatível** | Proxy IAP e Delta Watcher exigem autenticação IAM e ingress restrito. |

### 6.2 Org Policies que Podem Exigir Allowlist ou Adaptação no Projeto/Folder

| Constraint / Controle | O que Quebra se Estiver Travada | Exceção Mínima Segura (Folder/Projeto) | Alternativa sem Relaxar a Policy |
| :--- | :--- | :--- | :--- |
| `constraints/gcp.restrictServiceUsage` | Bloqueia APIs da Seção 3 (`ces`, `discoveryengine`, `aiplatform`, `texttospeech`, `oslogin`, `iap`, `iamcredentials`). | Liberar apenas as APIs da Seção 3 nos projetos da fábrica. | Não aplicável (APIs obrigatórias). |
| `constraints/gcp.resourceLocations` | Bloqueia CES multi-region `us`, bucket `US` ou endpoints Vertex AI `global`. | Permitir `in:us-locations` e `global` nos projetos de Inferência e Sandbox. | Ajustar `harnesses.vertex_gemini_location` / `vertex_claude_region` para região aprovada (`us`/`eu`/`us-east5`). |
| `constraints/iam.disableCrossProjectServiceAccountUsage` | Impede `<prefix>-hub@` de impersonar SAs em Inferência/Sandbox. | Isentar apenas o Folder da fábrica. | Adotar a **topologia de 1 projeto** (`hub == inference == sandbox`). |
| `constraints/iam.allowedPolicyMemberDomains` | Bloqueia contas externas no IAM/Hub e `billing-budget-alert@system.gserviceaccount.com` no Pub/Sub do Budget (`HC-04 F2`). | **Evite relaxar.** Conceda identidades do domínio do cliente aos FDEs ou defina `enable_budget_pubsub_topic = false`. | Operação 100% por principal do cliente + alertas de e-mail e cotas TPM. |
| `constraints/iam.workloadIdentityPoolProviders` | Bloqueia provedor OIDC `https://token.actions.githubusercontent.com`. | Liberar o issuer GitHub do cliente no Sandbox com `attribute_condition` travada em `owner/repo`. | Runner CI self-hosted dentro do GCP do cliente. |
| `constraints/compute.trustedImageProjects` | Bloqueia `ubuntu-os-cloud/ubuntu-2204-lts` na `lite-vm`. | Liberar `projects/ubuntu-os-cloud` no projeto do Hub. | Passar a Golden Image corporativa em `var.boot_image`. |
| `constraints/cloudbuild.allowedWorkerPools` | Bloqueia `gcloud builds submit` no pool padrão. | Autorizar pool privado corporativo no Hub. | Usar `--mode mirror` ou definir `options.pool.name`. |
| `constraints/gcp.restrictNonCmekServices` | Bloqueia disco/storage sem Cloud KMS. | Configurar chave CMEK em `var.boot_disk_kms_key_self_link` (suportado em `lite-vm/variables.tf`). | Stage 01 não possui variável KMS dedicada; aplicar CMEK no bucket/AR via módulo organizacional do cliente se obrigatório. |
| **VPC Service Controls (VPC-SC)** | Bloqueia egress para GitHub/PyPI ou chamadas cross-project. | Regras explícitas de ingress/egress entre Hub, Inferência e Sandbox. | Release Kit 100% offline (`--mode mirror` + binário Scion em mirror interno). |

### 6.3 Auditoria Obrigatória de Org Policies no Dia 0 (Read-Only)

```bash
for P in "$HUB_PROJECT_ID" "$INFERENCE_PROJECT_ID" "$SANDBOX_PROJECT_ID"; do
  echo "=== Effective Org Policies: $P ==="
  gcloud org-policies list --project="$P" --show-unset=false
done
```

---

## 7. Controles de FinOps e Limites Honestos

> [!NOTE]
> Os controles abaixo estabelecem exposição máxima calculável (`Cota TPM x latência do Cloud Billing`) e não garantem teto instantâneo zero risco. Qualquer estimativa de custo de referência considera exclusivamente preços públicos de tabela do Google Cloud e não cobre descontos ou acordos comerciais específicos do cliente.

1. **Projeto de Inferência dedicado** + **cotas explícitas de TPM** por modelo na Vertex AI (freio físico em tempo real).
2. **Limites determinísticos no Scion Hub:** `default_max_duration=2h`, `default_max_turns=60`, `default_max_model_calls=150` (validado em `HC-04 M5.6` com `exitCode=10`) e `server.hub.auto_suspend_idle=true` *(efetivo apenas quando o experimento upstream `lifecycle.idle_suspend` estiver habilitado no Hub)*.
3. **Budget Alert 70% / 90% + Tópico Pub/Sub (`finops.tf`):** o Stage 01 cria o orçamento e publica alertas no tópico `<name_prefix>-budget-alerts`. **Não há consumidor automático nem revogação IAM automática implantada pelo Stage 01 na `v0.6.0`.** A revogação de `vertexInferencePredict` de `<name_prefix>-worker@` é executada via runbook manual (`gcloud projects remove-iam-policy-binding`) ou via consumidor Pub/Sub próprio do cliente.

---

## 8. Limite Honesto do Sandbox (`not-verifiable-in-sandbox`)

- **GECX (`packs/gecx`):** valida texto, callbacks offline, tool unit tests, golden/simulation evals e áudio sintético (`Sessions.async_bidi_run_session`). **Não** simula tronco SIP, SBC, AudioCodes VAIC, áudio 8 kHz de operadora, DTMF ou transferência live para CCaaS.
- **ADK (`packs/adk`):** valida `pytest`, contrato `Dockerfile` nativo `agents-cli` (`ADR-014`), bundle `ge_export.py`, `adk eval` live e registro `[CI]` no Gemini Enterprise Sandbox. Conectores corporativos privados sem mock ou integrações OAuth de produção exigem aceite humano explícito.
- **Generic (`packs/generic`):** valida `build`/`lint`/`test` determinísticos via `generic_sandbox_gate.py --base-ref` e smoke `e2e` em Cloud Run Sandbox quando `deploy_target != none`. Sistemas legados externos ou ambientes regulados fora do Sandbox são listados explicitamente em `not_verifiable_in_sandbox` durante o `/grill-me`.

---

## 9. Checklist Go / No-Go (Antes do Dia 1)

- [ ] Auditoria read-only de Organization Policies (`gcloud org-policies list`) e VPC-SC executada nos projetos alvo.
- [ ] Projetos alvo criados e vinculados ao Billing Account (3, 2, 1 projeto ou exceção `enable_sandbox_project = false` para CI-only).
- [ ] `01-landing-zone` aplicado pela Plataforma/SecOps (com `enable_gecx_sandbox_roles`, `enable_adk_sandbox_roles`, `enable_generic_sandbox_roles`, `enable_github_wif`, `enable_kaizen_gcp_obs` e `enable_budget_pubsub_topic` conforme o pack e Org Policies) e `landing-zone-outputs.json` exportado.
- [ ] Grupo de operadores incluído em `factory_operator_members` e principal do cliente definido como dono do `coordinator`.
- [ ] Perfil de diversidade escolhido (`cross-model` padrão 1P Gemini ou `cross-vendor` com aceite manual de Claude no Model Garden) e cotas TPM configuradas.
- [ ] Repositório GitHub com branch protection em `main`, WIF configurado (`GCP_WIF_PROVIDER`), imagem digest pinada (`<PACK>_RUNTIME_IMAGE_DIGEST`) e labels `eval-change-approved` / `no-verdict-approved` criadas.
- [ ] Modo de entrega de imagem definido (`rebuild` com imagens base Scion ou `mirror` com digests reais) e verificado.
