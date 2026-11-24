# Required Google Cloud APIs per target project.
# Deduplicates project-API pairs automatically when two variables point to the same project.
# Includes oslogin.googleapis.com so IAP SSH succeeds on brand-new projects with enable-oslogin=TRUE.

locals {
  hub_apis = [
    "compute.googleapis.com",
    "oslogin.googleapis.com",
    "run.googleapis.com",
    "iap.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "pubsub.googleapis.com",
    "billingbudgets.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]

  inference_apis = [
    "aiplatform.googleapis.com",
    "serviceusage.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "billingbudgets.googleapis.com",
  ]

  sandbox_apis = concat(
    [
      "ces.googleapis.com",
      "aiplatform.googleapis.com",
      "texttospeech.googleapis.com",
      "storage.googleapis.com",
      "serviceusage.googleapis.com",
      "iamcredentials.googleapis.com",
      "logging.googleapis.com",
    ],
    var.enable_adk_sandbox_roles ? ["discoveryengine.googleapis.com"] : [],
  )

  project_api_pairs = merge(
    { for api in local.hub_apis : "${var.hub_project_id}/${api}" => { project = var.hub_project_id, api = api } },
    { for api in local.inference_apis : "${var.inference_project_id}/${api}" => { project = var.inference_project_id, api = api } },
    { for api in local.sandbox_apis : "${var.sandbox_project_id}/${api}" => { project = var.sandbox_project_id, api = api } },
  )
}

resource "google_project_service" "enabled" {
  for_each = local.project_api_pairs

  project            = each.value.project
  service            = each.value.api
  disable_on_destroy = false
}
