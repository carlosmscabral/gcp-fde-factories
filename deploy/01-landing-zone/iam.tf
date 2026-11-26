# Least-privilege Service Accounts and explicit non-wildcard Custom Roles for GECX Sandbox.
# Gate 0 Spike proved all 11 predefined roles/ces.* inherit 79 contactcenterinsights.* perms
# and ces.conversations.*, while roles/ces.appEditor omits agents, tools, toolsets, and guardrails.
# These 3 explicit Custom Roles enforce zero-PII isolation and full split-SA separation.

locals {
  unique_target_projects = toset(compact([
    var.hub_project_id,
    var.inference_project_id,
    var.enable_sandbox_project ? var.sandbox_project_id : "",
  ]))

  # Explicit read permissions for CES metadata without conversations or Insights.
  ces_metadata_read_perms = [
    "ces.agents.get",
    "ces.agents.list",
    "ces.appVersions.get",
    "ces.appVersions.list",
    "ces.apps.get",
    "ces.apps.list",
    "ces.changelogs.get",
    "ces.changelogs.list",
    "ces.deployments.get",
    "ces.deployments.list",
    "ces.evaluationDatasets.get",
    "ces.evaluationDatasets.list",
    "ces.evaluationExpectations.get",
    "ces.evaluationExpectations.list",
    "ces.evaluationResults.get",
    "ces.evaluationResults.list",
    "ces.evaluationRuns.get",
    "ces.evaluationRuns.list",
    "ces.evaluations.get",
    "ces.evaluations.list",
    "ces.examples.get",
    "ces.examples.list",
    "ces.guardrails.get",
    "ces.guardrails.list",
    "ces.locations.get",
    "ces.locations.list",
    "ces.operations.get",
    "ces.operations.list",
    "ces.securitySettings.get",
    "ces.tools.get",
    "ces.tools.list",
    "ces.toolsets.get",
    "ces.toolsets.list",
  ]

  # Deployer write permissions for ephemeral app lifecycle in Sandbox only.
  ces_deployer_write_perms = [
    "ces.agents.create",
    "ces.agents.delete",
    "ces.agents.update",
    "ces.appVersions.create",
    "ces.appVersions.delete",
    "ces.apps.create",
    "ces.apps.delete",
    "ces.apps.export",
    "ces.apps.import",
    "ces.apps.update",
    "ces.evaluationDatasets.create",
    "ces.evaluationDatasets.delete",
    "ces.evaluationDatasets.update",
    "ces.evaluationExpectations.create",
    "ces.evaluationExpectations.delete",
    "ces.evaluationExpectations.update",
    "ces.evaluations.create",
    "ces.evaluations.delete",
    "ces.evaluations.export",
    "ces.evaluations.update",
    "ces.examples.create",
    "ces.examples.delete",
    "ces.examples.update",
    "ces.guardrails.create",
    "ces.guardrails.delete",
    "ces.guardrails.update",
    "ces.tools.create",
    "ces.tools.delete",
    "ces.tools.update",
    "ces.toolsets.create",
    "ces.toolsets.delete",
    "ces.toolsets.update",
  ]

  # Evaluator execution permissions without app or agent write rights.
  ces_evaluator_exec_perms = [
    "ces.apps.runEvaluation",
    "ces.evaluations.export",
    "ces.sessions.bidiRunSession",
    "ces.sessions.runSession",
    "ces.tools.execute",
  ]

  # Assignable agent SAs eligible for human operator actAs grants under gcp_iam_check_mode=enforce.
  assignable_sa_map = merge(
    {
      coordinator = google_service_account.coordinator.name
      worker      = google_service_account.worker.name
    },
    var.enable_sandbox_project ? {
      deployer  = google_service_account.sandbox_deployer[0].name
      evaluator = google_service_account.sandbox_evaluator[0].name
    } : {},
    var.enable_kaizen_gcp_obs ? { kaizen_viewer = google_service_account.kaizen_viewer[0].name } : {},
  )

  operator_sa_pairs = merge([
    for member in var.factory_operator_members : {
      for slot, sa_name in local.assignable_sa_map :
      "${slot}/${member}" => { sa_name = sa_name, member = member }
    }
  ]...)
}

# --- Custom IAM Roles on Sandbox Project ---

resource "google_project_iam_custom_role" "gecx_sandbox_deployer" {
  count = var.enable_sandbox_project && var.enable_gecx_sandbox_roles ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "gecxSandboxDeployer"
  title       = "GECX Sandbox Ephemeral Deployer"
  description = "Creates, updates, and deletes ephemeral GECX apps in Sandbox without Insights or conversation read access."
  permissions = distinct(concat(local.ces_metadata_read_perms, local.ces_deployer_write_perms))

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_custom_role" "gecx_sandbox_evaluator" {
  count = var.enable_sandbox_project && var.enable_gecx_sandbox_roles ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "gecxSandboxEvaluator"
  title       = "GECX Sandbox Evaluator"
  description = "Runs GECX evaluations and synthetic sessions in Sandbox without mutating apps or reading Insights."
  permissions = distinct(concat(local.ces_metadata_read_perms, local.ces_evaluator_exec_perms))

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_custom_role" "gecx_sandbox_janitor" {
  count = var.enable_sandbox_project && var.enable_gecx_sandbox_roles ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "gecxSandboxJanitor"
  title       = "GECX Sandbox Ephemeral Janitor"
  description = "Lists and deletes expired ephemeral GECX apps in Sandbox."
  permissions = [
    "ces.apps.delete",
    "ces.apps.get",
    "ces.apps.list",
    "ces.locations.get",
    "ces.locations.list",
    "ces.operations.get",
    "ces.operations.list",
  ]

  depends_on = [google_project_service.enabled]
}

# Explicit predict-only Vertex AI role on Inference Project shared by worker, deployer, and eval SAs.
# Replaces roles/aiplatform.user on worker (HC-01 F26/F27: prevents worker from creating ReasoningEngines
# while enabling Vertex AI harness inference across all 3 assignable agent SAs).
resource "google_project_iam_custom_role" "inference_vertex_predict" {
  project     = var.inference_project_id
  role_id     = "vertexInferencePredict"
  title       = "Factory Vertex AI Predict-Only"
  description = "Allows Vertex AI model prediction calls for factory agents without ReasoningEngine or endpoint write rights."
  permissions = [
    "aiplatform.endpoints.predict",
  ]

  depends_on = [google_project_service.enabled]
}

# Explicit predict-only Vertex AI role for Sandbox Evaluator when sandbox_project_id differs from inference_project_id.
resource "google_project_iam_custom_role" "sandbox_evaluator_predict" {
  count = var.enable_sandbox_project ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "sandboxEvaluatorPredict"
  title       = "Sandbox Evaluator Predict-Only"
  description = "Allows model prediction calls during Sandbox evaluation without creating, updating, or deleting ReasoningEngines."
  permissions = [
    "aiplatform.endpoints.predict",
  ]

  depends_on = [google_project_service.enabled]
}

# --- Service Accounts (Additive bindings only, zero static JSON keys) ---

resource "google_service_account" "scion_hub" {
  project      = var.hub_project_id
  account_id   = "${var.name_prefix}-hub"
  display_name = "Scion Hub Server Runtime"
}

resource "google_service_account" "iap_proxy" {
  project      = var.hub_project_id
  account_id   = "${var.name_prefix}-iap"
  display_name = "Scion Cloud Run IAP Proxy (Zero Project Roles)"
}

resource "google_service_account" "coordinator" {
  project      = var.inference_project_id
  account_id   = "${var.name_prefix}-coordinator"
  display_name = "Scion Factory Coordinator (Predict and Child-SA Assign Only)"
}

resource "google_service_account" "worker" {
  project      = var.inference_project_id
  account_id   = "${var.name_prefix}-worker"
  display_name = "Scion SEP Workers (Inference Only)"
}

resource "google_service_account" "sandbox_deployer" {
  count = var.enable_sandbox_project ? 1 : 0

  project      = var.sandbox_project_id
  account_id   = "${var.name_prefix}-deployer"
  display_name = "Factory Sandbox Ephemeral Deployer"
}

resource "google_service_account" "sandbox_evaluator" {
  count = var.enable_sandbox_project ? 1 : 0

  project      = var.sandbox_project_id
  account_id   = "${var.name_prefix}-eval"
  display_name = "Factory Sandbox Evaluator"
}

resource "google_service_account" "sandbox_janitor" {
  count = var.enable_sandbox_project ? 1 : 0

  project      = var.sandbox_project_id
  account_id   = "${var.name_prefix}-janitor"
  display_name = "Factory Sandbox Hourly Janitor"
}

resource "google_service_account" "release_builder" {
  project      = var.hub_project_id
  account_id   = "${var.name_prefix}-builder"
  display_name = "Factory Release Kit Cloud Build SA (Rebuild Mode)"
}

resource "google_project_iam_member" "builder_ar_writer" {
  project = var.hub_project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.release_builder.email}"
}

resource "google_project_iam_member" "builder_logging" {
  project = var.hub_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.release_builder.email}"
}

resource "google_project_iam_member" "builder_storage_viewer" {
  project = var.hub_project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.release_builder.email}"
}

# Dedicated least-privilege GKE node SA when enable_gke_api is true (HC-02 F4).
# Prevents 403 ImagePullBackOff on hardened projects where the Compute Engine default SA lacks roles/editor.
resource "google_service_account" "gke_node" {
  count = var.enable_gke_api ? 1 : 0

  project      = var.hub_project_id
  account_id   = "${var.name_prefix}-gke-node"
  display_name = "Scion GKE Node Pool Runtime (Least Privilege)"
}

resource "google_project_iam_member" "gke_node_default" {
  count = var.enable_gke_api ? 1 : 0

  project = var.hub_project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = "serviceAccount:${google_service_account.gke_node[0].email}"
}

resource "google_project_iam_member" "gke_node_ar_reader" {
  count = var.enable_gke_api ? 1 : 0

  project = var.hub_project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.gke_node[0].email}"
}

# --- Scion Hub Server IAM (required by gcp_iam_check_mode=enforce + assign SA minting) ---

resource "google_project_iam_member" "hub_security_reviewer" {
  for_each = local.unique_target_projects

  project = each.value
  role    = "roles/iam.securityReviewer"
  member  = "serviceAccount:${google_service_account.scion_hub.email}"
}

resource "google_project_iam_member" "hub_ar_reader" {
  project = var.hub_project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.scion_hub.email}"
}

resource "google_project_iam_member" "hub_logging" {
  project = var.hub_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.scion_hub.email}"
}

# Grant token minting strictly on the assignable agent SAs (never on sandbox_janitor).
resource "google_service_account_iam_member" "hub_mint_coordinator" {
  service_account_id = google_service_account.coordinator.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.scion_hub.email}"
}

resource "google_service_account_iam_member" "hub_mint_worker" {
  service_account_id = google_service_account.worker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.scion_hub.email}"
}

resource "google_service_account_iam_member" "hub_mint_deployer" {
  count = var.enable_sandbox_project ? 1 : 0

  service_account_id = google_service_account.sandbox_deployer[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.scion_hub.email}"
}

resource "google_service_account_iam_member" "hub_mint_evaluator" {
  count = var.enable_sandbox_project ? 1 : 0

  service_account_id = google_service_account.sandbox_evaluator[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.scion_hub.email}"
}

# Grant actAs on the assignable SAs and Cloud Build submission rights to customer operators without Editor/Owner.
resource "google_service_account_iam_member" "operator_act_as" {
  for_each = local.operator_sa_pairs

  service_account_id = each.value.sa_name
  role               = "roles/iam.serviceAccountUser"
  member             = each.value.member
}

resource "google_service_account_iam_member" "operator_builder_act_as" {
  for_each = toset(var.factory_operator_members)

  service_account_id = google_service_account.release_builder.name
  role               = "roles/iam.serviceAccountUser"
  member             = each.value
}

resource "google_project_iam_member" "operator_cloudbuild_editor" {
  for_each = toset(var.factory_operator_members)

  project = var.hub_project_id
  role    = "roles/cloudbuild.builds.editor"
  member  = each.value
}

# Allow CI Evaluator and Sandbox Deployer SAs to pull digest-pinned images from the Hub Artifact Registry.
resource "google_project_iam_member" "evaluator_ar_reader" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.hub_project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.sandbox_evaluator[0].email}"
}

resource "google_project_iam_member" "deployer_ar_reader" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.hub_project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

# Materialize Sandbox Cloud Run and Vertex AI service agents so ADK containers pull from Hub Artifact Registry.
resource "google_project_service_identity" "sandbox_cloudrun_agent" {
  provider = google-beta
  count    = var.enable_sandbox_project && (var.enable_adk_sandbox_roles || var.enable_generic_sandbox_roles) ? 1 : 0

  project = var.sandbox_project_id
  service = "run.googleapis.com"

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_member" "sandbox_cloudrun_ar_reader" {
  count = var.enable_sandbox_project && (var.enable_adk_sandbox_roles || var.enable_generic_sandbox_roles) ? 1 : 0

  project = var.hub_project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_project_service_identity.sandbox_cloudrun_agent[0].email}"

  depends_on = [google_project_service_identity.sandbox_cloudrun_agent]
}

resource "google_project_service_identity" "sandbox_aiplatform_agent" {
  provider = google-beta
  count    = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  service = "aiplatform.googleapis.com"

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_member" "sandbox_aiplatform_ar_reader" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.hub_project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_project_service_identity.sandbox_aiplatform_agent[0].email}"

  depends_on = [google_project_service_identity.sandbox_aiplatform_agent]
}

# Optional binding for the Vertex AI Agent Engine dedicated Reasoning Engine service agent
# (gcp-sa-aiplatform-re), materialized after the first ReasoningEngine API call in sandbox_project_id.
resource "google_project_iam_member" "sandbox_agent_engine_re_ar_reader" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles && var.enable_agent_engine_re_ar_reader ? 1 : 0

  project = var.hub_project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:service-${data.google_project.sandbox[0].number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}

# --- Coordinator Least-Privilege Orchestration IAM (HC-10: Autonomous Split-SA Spawn) ---
# Scion Hub enforces Policy Troubleshooter actAs checks on the calling agent's assigned SA
# when a coordinator spawns child agents under a different SA (deployer, evaluator, kaizen).
# Keeping coordinator separate from worker preserves ADR-003: leaf workers hold zero actAs grants.
# Coordinator receives roles/iam.serviceAccountUser (actAs only, never TokenCreator, never janitor).

resource "google_project_iam_member" "coordinator_vertex_predict" {
  project = var.inference_project_id
  role    = google_project_iam_custom_role.inference_vertex_predict.id
  member  = "serviceAccount:${google_service_account.coordinator.email}"
}

resource "google_project_iam_member" "coordinator_service_usage" {
  project = var.inference_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.coordinator.email}"
}

resource "google_project_iam_member" "coordinator_logging" {
  project = var.inference_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.coordinator.email}"
}

resource "google_project_iam_member" "coordinator_monitoring" {
  project = var.inference_project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.coordinator.email}"
}

resource "google_service_account_iam_member" "coordinator_act_as_worker" {
  service_account_id = google_service_account.worker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.coordinator.email}"
}

resource "google_service_account_iam_member" "coordinator_act_as_deployer" {
  count = var.enable_sandbox_project ? 1 : 0

  service_account_id = google_service_account.sandbox_deployer[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.coordinator.email}"
}

resource "google_service_account_iam_member" "coordinator_act_as_evaluator" {
  count = var.enable_sandbox_project ? 1 : 0

  service_account_id = google_service_account.sandbox_evaluator[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.coordinator.email}"
}

resource "google_service_account_iam_member" "coordinator_act_as_kaizen" {
  count = var.enable_kaizen_gcp_obs ? 1 : 0

  service_account_id = google_service_account.kaizen_viewer[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.coordinator.email}"
}

# --- Inference Project Least-Privilege Predict-Only IAM (Worker, Deployer, Evaluator — HC-01 F26/F27) ---

resource "google_project_iam_member" "worker_vertex_predict" {
  project = var.inference_project_id
  role    = google_project_iam_custom_role.inference_vertex_predict.id
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "deployer_inference_vertex_predict" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.inference_project_id
  role    = google_project_iam_custom_role.inference_vertex_predict.id
  member  = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_project_iam_member" "evaluator_inference_vertex_predict" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.inference_project_id
  role    = google_project_iam_custom_role.inference_vertex_predict.id
  member  = "serviceAccount:${google_service_account.sandbox_evaluator[0].email}"
}

resource "google_project_iam_member" "worker_service_usage" {
  project = var.inference_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "deployer_inference_service_usage" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.inference_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_project_iam_member" "evaluator_inference_service_usage" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.inference_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.sandbox_evaluator[0].email}"
}

resource "google_project_iam_member" "worker_logging" {
  project = var.inference_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "worker_monitoring" {
  project = var.inference_project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

# --- Sandbox Project Split IAM ---

resource "google_project_iam_member" "deployer_custom_role" {
  count = var.enable_sandbox_project && var.enable_gecx_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.gecx_sandbox_deployer[0].id
  member  = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_project_iam_member" "deployer_service_usage" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.sandbox_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_project_iam_member" "evaluator_custom_role" {
  count = var.enable_sandbox_project && var.enable_gecx_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.gecx_sandbox_evaluator[0].id
  member  = "serviceAccount:${google_service_account.sandbox_evaluator[0].email}"
}

resource "google_project_iam_member" "evaluator_vertex_predict" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.sandbox_evaluator_predict[0].id
  member  = "serviceAccount:${google_service_account.sandbox_evaluator[0].email}"
}

resource "google_project_iam_member" "evaluator_service_usage" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.sandbox_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.sandbox_evaluator[0].email}"
}

resource "google_project_iam_member" "janitor_custom_role" {
  count = var.enable_sandbox_project && var.enable_gecx_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.gecx_sandbox_janitor[0].id
  member  = "serviceAccount:${google_service_account.sandbox_janitor[0].email}"
}

resource "google_project_iam_member" "janitor_service_usage" {
  count = var.enable_sandbox_project ? 1 : 0

  project = var.sandbox_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.sandbox_janitor[0].email}"
}

# --- Optional Multi-Pack ADK + Gemini Enterprise Sandbox Custom Roles (Explicit, Zero Wildcards) ---

resource "google_project_iam_custom_role" "adk_sandbox_deployer" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "adkSandboxDeployer"
  title       = "ADK and Gemini Enterprise Sandbox Ephemeral Deployer"
  description = "Builds ADK Docker images via Cloud Build, deploys ephemeral Agent Engine or Cloud Run runtimes, and registers ephemeral Sandbox agents in Gemini Enterprise."
  permissions = [
    "aiplatform.reasoningEngines.create",
    "aiplatform.reasoningEngines.delete",
    "aiplatform.reasoningEngines.get",
    "aiplatform.reasoningEngines.list",
    "aiplatform.reasoningEngines.query",
    "aiplatform.reasoningEngines.update",
    "cloudbuild.builds.create",
    "cloudbuild.builds.get",
    "cloudbuild.builds.list",
    "discoveryengine.agents.create",
    "discoveryengine.agents.delete",
    "discoveryengine.agents.get",
    "discoveryengine.agents.list",
    "discoveryengine.agents.manage",
    "discoveryengine.agents.update",
    "run.operations.get",
    "run.revisions.get",
    "run.revisions.list",
    "run.services.create",
    "run.services.delete",
    "run.services.get",
    "run.services.list",
    "run.services.update",
  ]

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_custom_role" "adk_sandbox_evaluator" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "adkSandboxEvaluator"
  title       = "ADK and Gemini Enterprise Sandbox Evaluator"
  description = "Queries ephemeral Vertex AI Agent Engine runtimes, invokes authenticated Cloud Run A2A services, and inspects Gemini Enterprise Sandbox agents without mutating them."
  permissions = [
    "aiplatform.reasoningEngines.get",
    "aiplatform.reasoningEngines.list",
    "aiplatform.reasoningEngines.query",
    "discoveryengine.agents.get",
    "discoveryengine.agents.list",
    "run.routes.invoke",
    "run.services.get",
    "run.services.list",
  ]

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_custom_role" "adk_sandbox_janitor" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "adkSandboxJanitor"
  title       = "ADK and Gemini Enterprise Sandbox Ephemeral Janitor"
  description = "Lists and deletes expired [CI] Vertex AI Agent Engine runtimes, Cloud Run services, and Gemini Enterprise Sandbox registrations."
  permissions = [
    "aiplatform.reasoningEngines.delete",
    "aiplatform.reasoningEngines.get",
    "aiplatform.reasoningEngines.list",
    "discoveryengine.agents.delete",
    "discoveryengine.agents.get",
    "discoveryengine.agents.list",
    "discoveryengine.agents.manage",
    "run.services.delete",
    "run.services.get",
    "run.services.list",
  ]

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_member" "deployer_adk_custom_role" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.adk_sandbox_deployer[0].id
  member  = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

# Allow ADK Sandbox Deployer to submit Dockerfile builds with the dedicated builder SA
# and attach the predict-only worker SA to ephemeral Sandbox Cloud Run services (HC-01 F29).
resource "google_service_account_iam_member" "deployer_builder_act_as" {
  count = var.enable_sandbox_project && (var.enable_adk_sandbox_roles || var.enable_generic_sandbox_roles) ? 1 : 0

  service_account_id = google_service_account.release_builder.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_service_account_iam_member" "deployer_worker_act_as" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  service_account_id = google_service_account.worker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

# Same-project Sandbox ADK Runtime SA for Cloud Run and Agent Engine workloads (HC-02 F10).
# Avoids cross-project SA attachment rejections under constraints/iam.disableCrossProjectServiceAccountUsage
# while holding predict-only rights on inference_project_id and zero write rights on sandbox_project_id.
resource "google_service_account" "adk_runtime" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project      = var.sandbox_project_id
  account_id   = "${var.name_prefix}-adk-runtime"
  display_name = "ADK Sandbox Container Runtime (Predict-Only)"
}

resource "google_service_account_iam_member" "deployer_adk_runtime_act_as" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  service_account_id = google_service_account.adk_runtime[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_project_iam_member" "adk_runtime_inference_predict" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.inference_project_id
  role    = google_project_iam_custom_role.inference_vertex_predict.id
  member  = "serviceAccount:${google_service_account.adk_runtime[0].email}"
}

resource "google_project_iam_member" "adk_runtime_inference_usage" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.inference_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.adk_runtime[0].email}"
}

resource "google_project_iam_member" "adk_runtime_sandbox_predict" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.sandbox_evaluator_predict[0].id
  member  = "serviceAccount:${google_service_account.adk_runtime[0].email}"
}

resource "google_project_iam_member" "adk_runtime_sandbox_usage" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.adk_runtime[0].email}"
}

resource "google_project_iam_member" "adk_runtime_hub_ar_reader" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.hub_project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.adk_runtime[0].email}"
}

resource "google_project_iam_member" "deployer_hub_cloudbuild_editor" {
  count = var.enable_sandbox_project && (var.enable_adk_sandbox_roles || var.enable_generic_sandbox_roles) && var.hub_project_id != var.sandbox_project_id ? 1 : 0

  project = var.hub_project_id
  role    = "roles/cloudbuild.builds.editor"
  member  = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_project_iam_member" "deployer_hub_service_usage" {
  count = var.enable_sandbox_project && (var.enable_adk_sandbox_roles || var.enable_generic_sandbox_roles) && var.hub_project_id != var.sandbox_project_id ? 1 : 0

  project = var.hub_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_project_iam_member" "evaluator_adk_custom_role" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.adk_sandbox_evaluator[0].id
  member  = "serviceAccount:${google_service_account.sandbox_evaluator[0].email}"
}

resource "google_project_iam_member" "janitor_adk_custom_role" {
  count = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.adk_sandbox_janitor[0].id
  member  = "serviceAccount:${google_service_account.sandbox_janitor[0].email}"
}

# --- Optional Tier-B Read-Only Kaizen Observability Service Account (v0.3.0) ---

resource "google_service_account" "kaizen_viewer" {
  count = var.enable_kaizen_gcp_obs ? 1 : 0

  project      = var.inference_project_id
  account_id   = "${var.name_prefix}-kaizen"
  display_name = "Factory Kaizen Read-Only Telemetry Viewer"
}

resource "google_service_account_iam_member" "hub_mint_kaizen_viewer" {
  count = var.enable_kaizen_gcp_obs ? 1 : 0

  service_account_id = google_service_account.kaizen_viewer[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.scion_hub.email}"
}

resource "google_project_iam_member" "kaizen_inference_monitoring" {
  count = var.enable_kaizen_gcp_obs ? 1 : 0

  project = var.inference_project_id
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${google_service_account.kaizen_viewer[0].email}"
}

# Allow kaizen_viewer to invoke Vertex AI predict and bill Monitoring calls when kaizen-analyst runs under it (HC-04 F5).
resource "google_project_iam_member" "kaizen_inference_predict" {
  count = var.enable_kaizen_gcp_obs ? 1 : 0

  project = var.inference_project_id
  role    = google_project_iam_custom_role.inference_vertex_predict.id
  member  = "serviceAccount:${google_service_account.kaizen_viewer[0].email}"
}

resource "google_project_iam_member" "kaizen_inference_usage" {
  count = var.enable_kaizen_gcp_obs ? 1 : 0

  project = var.inference_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.kaizen_viewer[0].email}"
}

resource "google_project_iam_member" "kaizen_sandbox_logging" {
  count = var.enable_sandbox_project && var.enable_kaizen_gcp_obs ? 1 : 0

  project = var.sandbox_project_id
  role    = "roles/logging.viewer"
  member  = "serviceAccount:${google_service_account.kaizen_viewer[0].email}"
}

# Grant Service Usage Consumer on sandbox_project_id so Cloud Logging clients sending x-goog-user-project avoid HTTP 403 (HC-04 F5).
resource "google_project_iam_member" "kaizen_sandbox_usage" {
  count = var.enable_sandbox_project && var.enable_kaizen_gcp_obs ? 1 : 0

  project = var.sandbox_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.kaizen_viewer[0].email}"
}

# --- Optional Keyless GitHub Actions Workload Identity Federation (for PR Verdict Gate + Janitor) ---

resource "google_iam_workload_identity_pool" "github_actions" {
  count = var.enable_sandbox_project && var.enable_github_wif ? 1 : 0

  project                   = var.sandbox_project_id
  workload_identity_pool_id = "${var.name_prefix}-gh-pool"
  display_name              = "GitHub Actions Verdict Gate Pool"
  description               = "Keyless OIDC federation strictly scoped to the customer repository for PR Verdict verification."

  depends_on = [google_project_service.enabled]
}

resource "google_iam_workload_identity_pool_provider" "github_oidc" {
  count = var.enable_sandbox_project && var.enable_github_wif ? 1 : 0

  project                            = var.sandbox_project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_actions[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub Actions OIDC Provider"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.actor"      = "assertion.actor"
  }
  attribute_condition = "assertion.repository == '${var.github_repository}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "wif_evaluator_impersonation" {
  count = var.enable_sandbox_project && var.enable_github_wif ? 1 : 0

  service_account_id = google_service_account.sandbox_evaluator[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_actions[0].name}/attribute.repository/${var.github_repository}"
}

resource "google_service_account_iam_member" "wif_janitor_impersonation" {
  count = var.enable_sandbox_project && var.enable_github_wif ? 1 : 0

  service_account_id = google_service_account.sandbox_janitor[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_actions[0].name}/attribute.repository/${var.github_repository}"
}
