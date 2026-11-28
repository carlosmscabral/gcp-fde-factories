# Example Stage 01 variables for a 3-project production topology.
# For a 2-project pilot, set inference_project_id equal to hub_project_id.
# For a 1-project pilot, set all three project IDs to the same project.

hub_project_id       = "customer-scion-hub"
inference_project_id = "customer-scion-inference"
sandbox_project_id   = "customer-gecx-sandbox"

region             = "us-central1"
zone               = "us-central1-a"
name_prefix        = "gecx-fac"
billing_account_id = "012345-6789AB-CDEF01"
monthly_budget_usd = 500

# Set create_custom_vpc = false and provide existing_subnet_self_link for Shared VPC.
create_custom_vpc = true
subnet_cidr       = "10.42.0.0/20"

# Customer operators who start coordinator and assign factory SAs under gcp_iam_check_mode=enforce.
factory_operator_members = [
  "group:gecx-factory-operators@example.com",
]

# Pack Sandbox role toggles (IMPORTANT: enable_gecx_sandbox_roles defaults to true in variables.tf).
# For packs/adk or packs/generic, explicitly set enable_gecx_sandbox_roles = false to avoid creating CES roles/APIs.
enable_sandbox_project       = true
enable_gecx_sandbox_roles    = true
enable_adk_sandbox_roles     = false
enable_generic_sandbox_roles = false

# Optional extras (GitHub WIF requires enable_sandbox_project = true; set enable_budget_pubsub_topic = false under DRS).
enable_github_wif          = false
github_repository          = ""
enable_kaizen_gcp_obs      = false
enable_budget_pubsub_topic = true
