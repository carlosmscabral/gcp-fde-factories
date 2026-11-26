# Narrow least-privilege Cloud Run Sandbox Custom Roles for packs/generic (ADR-016, H7).
# Grants Cloud Run and Cloud Build lifecycle permissions only, without Agent Engine, Discovery Engine,
# or CES/GECX permissions. Enabled strictly when both enable_sandbox_project and enable_generic_sandbox_roles are true.

resource "google_project_iam_custom_role" "generic_sandbox_deployer" {
  count = var.enable_sandbox_project && var.enable_generic_sandbox_roles ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "genericSandboxDeployer"
  title       = "Generic Software Sandbox Ephemeral Deployer"
  description = "Builds container images via Cloud Build and deploys ephemeral Cloud Run services in Sandbox without ADK or CES permissions."
  permissions = [
    "cloudbuild.builds.create",
    "cloudbuild.builds.get",
    "cloudbuild.builds.list",
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

resource "google_project_iam_custom_role" "generic_sandbox_evaluator" {
  count = var.enable_sandbox_project && var.enable_generic_sandbox_roles ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "genericSandboxEvaluator"
  title       = "Generic Software Sandbox Evaluator"
  description = "Invokes and inspects ephemeral Sandbox Cloud Run services without write permissions."
  permissions = [
    "run.routes.invoke",
    "run.services.get",
    "run.services.list",
  ]

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_custom_role" "generic_sandbox_janitor" {
  count = var.enable_sandbox_project && var.enable_generic_sandbox_roles ? 1 : 0

  project     = var.sandbox_project_id
  role_id     = "genericSandboxJanitor"
  title       = "Generic Software Sandbox Ephemeral Janitor"
  description = "Lists and deletes expired [CI] Cloud Run services in Sandbox."
  permissions = [
    "run.services.delete",
    "run.services.get",
    "run.services.list",
  ]

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_member" "deployer_generic_custom_role" {
  count = var.enable_sandbox_project && var.enable_generic_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.generic_sandbox_deployer[0].id
  member  = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_project_iam_member" "evaluator_generic_custom_role" {
  count = var.enable_sandbox_project && var.enable_generic_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.generic_sandbox_evaluator[0].id
  member  = "serviceAccount:${google_service_account.sandbox_evaluator[0].email}"
}

resource "google_project_iam_member" "janitor_generic_custom_role" {
  count = var.enable_sandbox_project && var.enable_generic_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  role    = google_project_iam_custom_role.generic_sandbox_janitor[0].id
  member  = "serviceAccount:${google_service_account.sandbox_janitor[0].email}"
}
