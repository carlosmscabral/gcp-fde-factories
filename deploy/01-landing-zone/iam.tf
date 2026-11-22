# Least-privilege Service Accounts and explicit non-wildcard Custom Roles for GECX Sandbox.
# Gate 0 Spike proved all 11 predefined roles/ces.* inherit 79 contactcenterinsights.* perms
# and ces.conversations.*, while roles/ces.appEditor omits agents, tools, toolsets, and guardrails.
# These 3 explicit Custom Roles enforce zero-PII isolation and full split-SA separation.

locals {
  unique_target_projects = toset([
    var.hub_project_id,
    var.inference_project_id,
    var.sandbox_project_id,
  ])

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
  assignable_sa_map = {
    worker    = google_service_account.worker.name
    deployer  = google_service_account.sandbox_deployer.name
    evaluator = google_service_account.sandbox_evaluator.name
  }

  operator_sa_pairs = merge([
    for member in var.factory_operator_members : {
      for slot, sa_name in local.assignable_sa_map :
      "${slot}/${member}" => { sa_name = sa_name, member = member }
    }
  ]...)
}

# --- Custom IAM Roles on Sandbox Project ---

resource "google_project_iam_custom_role" "gecx_sandbox_deployer" {
  project     = var.sandbox_project_id
  role_id     = "gecxSandboxDeployer"
  title       = "GECX Sandbox Ephemeral Deployer"
  description = "Creates, updates, and deletes ephemeral GECX apps in Sandbox without Insights or conversation read access."
  permissions = distinct(concat(local.ces_metadata_read_perms, local.ces_deployer_write_perms))

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_custom_role" "gecx_sandbox_evaluator" {
  project     = var.sandbox_project_id
  role_id     = "gecxSandboxEvaluator"
  title       = "GECX Sandbox Evaluator"
  description = "Runs GECX evaluations and synthetic sessions in Sandbox without mutating apps or reading Insights."
  permissions = distinct(concat(local.ces_metadata_read_perms, local.ces_evaluator_exec_perms))

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_custom_role" "gecx_sandbox_janitor" {
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

resource "google_service_account" "worker" {
  project      = var.inference_project_id
  account_id   = "${var.name_prefix}-worker"
  display_name = "Scion SEP Workers (Inference Only)"
}

resource "google_service_account" "sandbox_deployer" {
  project      = var.sandbox_project_id
  account_id   = "${var.name_prefix}-deployer"
  display_name = "GECX Sandbox Ephemeral Deployer"
}

resource "google_service_account" "sandbox_evaluator" {
  project      = var.sandbox_project_id
  account_id   = "${var.name_prefix}-eval"
  display_name = "GECX Sandbox Evaluator"
}

resource "google_service_account" "sandbox_janitor" {
  project      = var.sandbox_project_id
  account_id   = "${var.name_prefix}-janitor"
  display_name = "GECX Sandbox Hourly Janitor"
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

# Grant token minting strictly on the 3 assignable agent SAs (never on sandbox_janitor).
resource "google_service_account_iam_member" "hub_mint_worker" {
  service_account_id = google_service_account.worker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.scion_hub.email}"
}

resource "google_service_account_iam_member" "hub_mint_deployer" {
  service_account_id = google_service_account.sandbox_deployer.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.scion_hub.email}"
}

resource "google_service_account_iam_member" "hub_mint_evaluator" {
  service_account_id = google_service_account.sandbox_evaluator.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.scion_hub.email}"
}

# Grant actAs on the 3 assignable SAs to customer operators so they pass enforce without Editor/Owner.
resource "google_service_account_iam_member" "operator_act_as" {
  for_each = local.operator_sa_pairs

  service_account_id = each.value.sa_name
  role               = "roles/iam.serviceAccountUser"
  member             = each.value.member
}

# --- Inference Project Worker IAM ---

resource "google_project_iam_member" "worker_vertex" {
  project = var.inference_project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "worker_service_usage" {
  project = var.inference_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.worker.email}"
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
  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.gecx_sandbox_deployer.id
  member  = "serviceAccount:${google_service_account.sandbox_deployer.email}"
}

resource "google_project_iam_member" "deployer_service_usage" {
  project = var.sandbox_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.sandbox_deployer.email}"
}

resource "google_project_iam_member" "evaluator_custom_role" {
  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.gecx_sandbox_evaluator.id
  member  = "serviceAccount:${google_service_account.sandbox_evaluator.email}"
}

resource "google_project_iam_member" "evaluator_vertex_sim" {
  project = var.sandbox_project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.sandbox_evaluator.email}"
}

resource "google_project_iam_member" "evaluator_service_usage" {
  project = var.sandbox_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.sandbox_evaluator.email}"
}

resource "google_project_iam_member" "janitor_custom_role" {
  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.gecx_sandbox_janitor.id
  member  = "serviceAccount:${google_service_account.sandbox_janitor.email}"
}

resource "google_project_iam_member" "janitor_service_usage" {
  project = var.sandbox_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.sandbox_janitor.email}"
}
