#!/usr/bin/env bash
# Stage 03 Hub Bootstrap reconciler (Contract 2: preflight / plan / backup / apply / rollback / overlay-sync).
# Enforces compat.yaml closed version checks, Scion v0.4.0-preview.3 CLI contracts
# (`harness-config sync <name> --global`, `schedule list --show recurring`), fail-closed
# image validation (rejects REPLACE_ / zero-digest harness images), default weekly Kaizen
# scheduling, and strict overlay skill budget + collision verification.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-}"
KIT_DIR=""
LANDING_ZONE_JSON=""
HUB_URL=""
PROJECT_SLUG=""
TARGET_REPO=""
BACKUP_DIR=""
HARNESS_IMAGE_ANTIGRAVITY=""
HARNESS_IMAGE_CLAUDE=""
START_COORDINATOR="auto"
TMP_CLEANUP_DIRS=()
PROJ_FLAGS=()

cleanup_tmp() {
  local d
  for d in "${TMP_CLEANUP_DIRS[@]:-}"; do
    if [[ -n "$d" && -d "$d" ]]; then
      rm -rf "$d"
    fi
  done
  return 0
}
trap cleanup_tmp EXIT

usage() {
  cat <<'EOF'
Usage: bootstrap-hub-project.sh <preflight|plan|backup|apply|rollback|overlay-sync> \
  --kit <release-kit-dir> --hub <https-or-loopback-url> \
  [--landing-zone <landing-zone-outputs.json>] [--repo <target-repo-dir>] [--backup-dir <dir>] \
  [--harness-image-antigravity <digest-or-registry-ref>] [--harness-image-claude <digest-or-registry-ref>] \
  [--start-coordinator | --no-start-coordinator]
EOF
  exit 2
}

shift || usage
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kit) KIT_DIR="$2"; shift 2 ;;
    --hub) HUB_URL="$2"; shift 2 ;;
    --project) PROJECT_SLUG="$2"; shift 2 ;;
    --landing-zone) LANDING_ZONE_JSON="$2"; shift 2 ;;
    --repo) TARGET_REPO="$2"; shift 2 ;;
    --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
    --harness-image-antigravity) HARNESS_IMAGE_ANTIGRAVITY="$2"; shift 2 ;;
    --harness-image-claude) HARNESS_IMAGE_CLAUDE="$2"; shift 2 ;;
    --start-coordinator) START_COORDINATOR="true"; shift ;;
    --no-start-coordinator) START_COORDINATOR="false"; shift ;;
    *) echo "Unknown flag: $1" >&2; usage ;;
  esac
done

[[ -n "$KIT_DIR" && -n "$HUB_URL" ]] || usage
export SCION_HUB_ENDPOINT="$HUB_URL"
if [[ -n "$PROJECT_SLUG" ]]; then
  PROJ_FLAGS=(--project "$PROJECT_SLUG")
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required CLI: $1" >&2; exit 1; }
}

parse_repo_cfg() {
  local pack_name="$1"
  if [[ -n "$TARGET_REPO" && -f "$TARGET_REPO/.factory/hub-project.yaml" ]]; then
    require_cmd python3
    python3 "$SCRIPT_DIR/parse_hub_project.py" --repo "$TARGET_REPO" --expected-pack "$pack_name"
  else
    cat <<'JSON'
{"pack":"","mode":"sandbox-direct","deploy_target":"","existing_hub":false,"diversity_profile":"cross-model","limits":{"default_max_duration":"2h","default_max_turns":60,"default_max_model_calls":150,"auto_suspend_idle":true},"exclude_skills":[],"overlay_skills":[],"kaizen":{"enabled":true,"schedule_cron":"0 17 * * 5","time_zone":"America/Sao_Paulo","coordinator_agent":"coordinator","enable_gcp_obs":false},"harnesses":{"default":"antigravity-vertex","claude_model_garden_enabled":false,"vertex_gemini_location":"global","vertex_claude_region":"global"},"model_routing":{},"monorepo":{"enabled":false,"subdir":"","agent_prefix":""},"roster":{"enabled_roles":[],"disabled_roles":[],"max_wip":3,"reviewer_replicas":1}}
JSON
  fi
}

do_preflight() {
  require_cmd scion
  require_cmd jq
  local version_out tested_list
  version_out="$(scion version 2>&1 | grep -Eo 'v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?' | head -n 1 | sed 's/\.$//' || true)"
  tested_list="$(jq -re '.scion_tested[]' "$KIT_DIR/manifest.json")"
  if ! grep -Fxq "$version_out" <<< "$tested_list"; then
    echo "PREFLIGHT FAILED: Scion version '${version_out:-unknown}' is not in compat.yaml closed tested list." >&2
    exit 1
  fi
  echo "PREFLIGHT OK: Scion $version_out matched compat.yaml tested list."
  if [[ ! -d ".scion" && ( -z "$TARGET_REPO" || ! -d "$TARGET_REPO/.scion" ) ]]; then
    echo "PREFLIGHT NOTE: No local .scion grove detected in $(pwd). Run apply from a linked Scion project directory so project-scoped commands succeed."
  fi
  scion hub status --hub "$HUB_URL"
}

do_plan() {
  do_preflight
  local pack_name pack_prefix repo_cfg disabled_roles_json mode deploy_target coord_tpl has_brief="false"
  pack_name="$(jq -re '.pack' "$KIT_DIR/manifest.json")"
  pack_prefix="$(jq -re '.pack_prefix // .pack' "$KIT_DIR/manifest.json")"
  repo_cfg="$(parse_repo_cfg "$pack_name")"
  disabled_roles_json="$(jq -c '.roster.disabled_roles // []' <<< "$repo_cfg")"
  mode="$(jq -re '.mode' <<< "$repo_cfg")"
  deploy_target="$(jq -r '.deploy_target // ""' <<< "$repo_cfg")"
  coord_tpl="${pack_prefix}-coordinator"
  if [[ -n "$TARGET_REPO" && -f "$TARGET_REPO/.factory/coordinator-bootstrap-brief.md" ]]; then
    has_brief="true"
  fi

  echo "=== PLAN: Pack Templates (Prefix-Scoped, Roster-Filtered) ==="
  for tpl_dir in "$KIT_DIR"/templates/*; do
    [[ -d "$tpl_dir" ]] || continue
    local tname role_short is_disabled
    tname="$(basename "$tpl_dir")"
    role_short="${tname#"${pack_prefix}-"}"
    is_disabled="$(jq -r --arg full "$tname" --arg short "$role_short" 'index($full) != null or index($short) != null' <<< "$disabled_roles_json")"
    if [[ "$is_disabled" == "true" ]]; then
      echo "${tname} [SKIP - disabled in roster]"
    else
      echo "${tname}"
    fi
  done
  echo "=== PLAN: Hub Skill Bank Skills ==="
  ls -1 "$KIT_DIR/skills"
  if [[ -d "$KIT_DIR/harness-configs" ]]; then
    echo "=== PLAN: Harness Configs ==="
    ls -1 "$KIT_DIR/harness-configs"
  fi
  echo "=== PLAN: Execution Mode and Coordinator Standby ==="
  echo "mode=${mode} deploy_target=${deploy_target:-default}"
  if [[ "$mode" == "sandbox-direct" && "$deploy_target" != "none" ]]; then
    echo "sandbox_service_accounts=register"
  else
    echo "sandbox_service_accounts=skip"
  fi
  if [[ "$START_COORDINATOR" == "false" || -z "$TARGET_REPO" || ( "$START_COORDINATOR" == "auto" && "$has_brief" != "true" ) ]]; then
    echo "coordinator_auto_start=skip (${coord_tpl})"
  else
    echo "coordinator_auto_start=enabled (${coord_tpl}, standby via --task-file)"
  fi
  echo "=== PLAN: Current Hub Template Status ==="
  scion templates status --hub "$HUB_URL" || true
}

do_backup() {
  local ts dir pulled=0
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  dir="${BACKUP_DIR:-$(pwd)/.backups/$ts}"
  mkdir -p "$dir/templates"
  echo "=== BACKUP: Exporting Hub settings and existing templates to $dir ==="
  scion hub settings get --section gcp_iam --hub "$HUB_URL" > "$dir/gcp_iam.txt"
  scion hub settings get --section agent_defaults --hub "$HUB_URL" > "$dir/agent_defaults.txt"
  scion templates list "${PROJ_FLAGS[@]}" --hub "$HUB_URL" > "$dir/templates_list.txt"
  for tpl_dir in "$KIT_DIR"/templates/*; do
    [[ -d "$tpl_dir" ]] || continue
    local name
    name="$(basename "$tpl_dir")"
    if scion templates pull "$name" "${PROJ_FLAGS[@]}" --hub "$HUB_URL" --to "$dir/templates/$name" 2>/dev/null; then
      pulled=$((pulled + 1))
    fi
  done
  jq -n --arg ts "$ts" --argjson templates_backed_up "$pulled" \
    '{timestamp_utc: $ts, templates_backed_up: $templates_backed_up, settings_saved: true}' \
    > "$dir/backup-manifest.json"
  echo "BACKUP COMPLETE: $dir (templates_backed_up=$pulled)"
}

UUID_REGEX='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'

validate_uuid_or_fail() {
  local val="$1" src="$2"
  if [[ ! "$val" =~ $UUID_REGEX ]]; then
    echo "ERROR: Invalid Hub project UUID '${val}' from ${src}." >&2
    return 1
  fi
}

resolve_project_id() {
  # Resolves and UUID-validates the Hub project UUID with strict precedence and mismatch checks (HC-10 F3, HC-11 F3, costela H4).
  # If TARGET_REPO is provided, reads only TARGET_REPO/.scion/ (never CWD).
  # If --project <slug> is provided, verifies the slug resolves to the exact same UUID so writes never split-brain.
  local env_pid="${SCION_HUB_PROJECT_ID:-}" file_pid="" slug_pid=""
  if [[ -n "$env_pid" ]]; then
    echo "WARNING: Inherited SCION_HUB_PROJECT_ID='${env_pid}' from parent shell; validating before use." >&2
    validate_uuid_or_fail "$env_pid" "SCION_HUB_PROJECT_ID" || return 1
  fi

  local base_dir="."
  if [[ -n "$TARGET_REPO" ]]; then
    base_dir="$TARGET_REPO"
  fi
  if [[ -f "${base_dir}/.scion/settings.yaml" ]]; then
    require_cmd python3
    file_pid="$(python3 "$SCRIPT_DIR/parse_hub_project.py" --read-scion-project-id "${base_dir}/.scion/settings.yaml")"
  elif [[ -f "${base_dir}/.scion/project-id" ]]; then
    file_pid="$(tr -d '[:space:]' < "${base_dir}/.scion/project-id")"
  fi
  if [[ -n "$file_pid" ]]; then
    validate_uuid_or_fail "$file_pid" "${base_dir}/.scion" || return 1
  fi

  if [[ -n "$PROJECT_SLUG" && -n "${SCION_HUB_TOKEN:-}" ]]; then
    slug_pid="$(curl -sf -H "Authorization: Bearer ${SCION_HUB_TOKEN}" "${HUB_URL%/}/api/v1/projects" \
      | jq -r --arg s "$PROJECT_SLUG" '((if type == "array" then . else (.projects // .items // []) end)[] | select(.slug == $s or .name == $s) | .id) // empty' | head -n 1 || true)"
    if [[ -n "$slug_pid" ]]; then
      validate_uuid_or_fail "$slug_pid" "--project ${PROJECT_SLUG}" || return 1
    fi
  fi

  if [[ -n "$slug_pid" && -n "$env_pid" && "$slug_pid" != "$env_pid" ]]; then
    echo "ERROR: --project '${PROJECT_SLUG}' (${slug_pid}) conflicts with inherited SCION_HUB_PROJECT_ID (${env_pid})." >&2
    return 1
  fi
  if [[ -n "$slug_pid" && -n "$file_pid" && "$slug_pid" != "$file_pid" ]]; then
    echo "ERROR: --project '${PROJECT_SLUG}' (${slug_pid}) conflicts with ${base_dir}/.scion (${file_pid})." >&2
    return 1
  fi

  local chosen="${slug_pid:-${file_pid:-$env_pid}}"
  if [[ -n "$chosen" ]]; then
    export SCION_HUB_PROJECT_ID="$chosen"
    echo "$chosen"
    return 0
  fi
  echo ""
}

warn_github_token_injection_mode() {
  # Warns when a linked project lacks GITHUB_TOKEN with injectionMode=always (required for private git clones, HC-10 F4, L6).
  local proj_id="$1"
  [[ -n "$proj_id" && -n "${SCION_HUB_TOKEN:-}" ]] || return 0
  validate_uuid_or_fail "$proj_id" "warn_github_token_injection_mode" || return 0
  local sec_json mode
  sec_json="$(curl -sf -H "Authorization: Bearer ${SCION_HUB_TOKEN}" "${HUB_URL%/}/api/v1/secrets?scope=project&scopeId=${proj_id}" 2>/dev/null || true)"
  [[ -n "$sec_json" ]] || return 0
  mode="$(jq -r '((.secrets // .)[]? | select(.key == "GITHUB_TOKEN") | (.injectionMode // .injection_mode)) // empty' <<< "$sec_json" | head -n 1 || true)"
  if [[ "$mode" != "always" ]]; then
    echo "WARNING: Project secret GITHUB_TOKEN has injectionMode='${mode:-missing}' (expected 'always' for private GitHub repo clones)." >&2
    echo "  Run: scion hub secret set --project GITHUB_TOKEN \"\$(gh auth token)\" --hub \"$HUB_URL\"" >&2
    echo "  Run: scion hub secret update --project GITHUB_TOKEN --injection-mode always --hub \"$HUB_URL\"" >&2
  fi
}

warn_adk_ge_license_preflight() {
  # Checks Discovery Engine project licenseConfigs on ADK sandboxes before waves start (HC-12 GE preflight).
  # Uses operator gcloud credentials best-effort; never fails offline tests or blocks Agent Engine deploys.
  local pack_name="$1"
  [[ "$pack_name" == "adk" && -n "$LANDING_ZONE_JSON" && -f "$LANDING_ZONE_JSON" ]] || return 0
  command -v gcloud >/dev/null 2>&1 || return 0
  command -v curl >/dev/null 2>&1 || return 0
  local sbx_p sbx_num token lc_json active_cnt
  sbx_p="$(jq -r '.sandbox_project_id.value // empty' "$LANDING_ZONE_JSON")"
  sbx_num="$(jq -r '.sandbox_project_number.value // empty' "$LANDING_ZONE_JSON")"
  [[ -n "$sbx_p" ]] || return 0
  token="$(gcloud auth print-access-token 2>/dev/null || true)"
  [[ -n "$token" ]] || return 0
  lc_json="$(curl -sf -H "Authorization: Bearer ${token}" -H "x-goog-user-project: ${sbx_p}" \
    "https://discoveryengine.googleapis.com/v1alpha/projects/${sbx_num:-$sbx_p}/locations/global/licenseConfigs" 2>/dev/null || true)"
  [[ -n "$lc_json" ]] || return 0
  active_cnt="$(jq -r '[(.licenseConfigs // [])[] | select((.state // "") == "ACTIVE")] | length' <<< "$lc_json" 2>/dev/null || echo "")"
  if [[ "$active_cnt" == "0" ]]; then
    echo "WARNING: Sandbox project '${sbx_p}' (${sbx_num:-unknown}) has 0 ACTIVE Gemini Enterprise licenseConfigs." >&2
    echo "  Vertex AI Agent Engine deploys and ge_export.py export will succeed, but live GE App agents:create will return HTTP 400 (licensing, not IAM)." >&2
    echo "  Distribute an active billingAccountLicenseConfig (or request free Argolis GE Plus project seats) before expecting live GE App registration." >&2
  fi
  return 0
}

print_github_ci_variables() {
  # Prints copy-ready GitHub Actions variable commands matching the pack's Verdict Gate workflow (HC-10 F5, L5).
  local pack_name="$1"
  [[ -n "$LANDING_ZONE_JSON" && -f "$LANDING_ZONE_JSON" ]] || return 0
  local wif_prov sbx_p sbx_num eval_sa jan_sa rt_img var_prefix
  wif_prov="$(jq -r '.github_wif_provider_name.value // empty' "$LANDING_ZONE_JSON")"
  sbx_p="$(jq -r '.sandbox_project_id.value // empty' "$LANDING_ZONE_JSON")"
  sbx_num="$(jq -r '.sandbox_project_number.value // empty' "$LANDING_ZONE_JSON")"
  eval_sa="$(jq -r '.sandbox_evaluator_sa_email.value // empty' "$LANDING_ZONE_JSON")"
  jan_sa="$(jq -r '.sandbox_janitor_sa_email.value // empty' "$LANDING_ZONE_JSON")"
  rt_img="$(jq -r --arg k "${pack_name}-runtime" '.images[$k] // empty' "$KIT_DIR/manifest.json")"
  case "$pack_name" in
    adk) var_prefix="ADK" ;;
    gecx) var_prefix="GECX" ;;
    *) return 0 ;;
  esac
  echo "=== NEXT STEP: GitHub Actions Verdict Gate Repository Variables (${pack_name}) ==="
  if [[ -n "$sbx_p" ]]; then echo "  gh variable set ${var_prefix}_SANDBOX_PROJECT_ID --body \"${sbx_p}\""; fi
  if [[ -n "$sbx_num" ]]; then echo "  gh variable set ${var_prefix}_SANDBOX_PROJECT_NUMBER --body \"${sbx_num}\""; fi
  if [[ -n "$eval_sa" ]]; then echo "  gh variable set ${var_prefix}_EVALUATOR_SA_EMAIL --body \"${eval_sa}\""; fi
  if [[ -n "$jan_sa" ]]; then echo "  gh variable set ${var_prefix}_JANITOR_SA_EMAIL --body \"${jan_sa}\""; fi
  if [[ -n "$rt_img" ]]; then echo "  gh variable set ${var_prefix}_RUNTIME_IMAGE_DIGEST --body \"${rt_img}\""; fi
  if [[ -n "$wif_prov" ]]; then echo "  gh variable set GCP_WIF_PROVIDER --body \"${wif_prov}\""; fi
  return 0
}

register_and_verify_sa() {
  local sa_email="$1" project_id="$2" label="$3"
  local sa_list_json existing_id sa_id
  local sa_proj_flags=("${PROJ_FLAGS[@]}")
  # Omit --project on `scion service-accounts` when SCION_HUB_PROJECT_ID is exported (HC-02 F5).
  if [[ -n "${SCION_HUB_PROJECT_ID:-}" ]]; then
    sa_proj_flags=()
  fi
  sa_list_json="$(scion --format json service-accounts list "${sa_proj_flags[@]}" --hub "$HUB_URL")"
  existing_id="$(jq -r --arg email "$sa_email" '((if type == "array" then . else (.serviceAccounts // .items // []) end)[] | select(.email == $email) | .id) // empty' <<< "$sa_list_json" | head -n 1)"
  if [[ -n "$existing_id" ]]; then
    sa_id="$existing_id"
    echo "EXISTING SA: $label ($sa_email -> $sa_id)"
  else
    sa_id="$(scion service-accounts add "$sa_email" --gcp-project "$project_id" --name "$label" "${sa_proj_flags[@]}" --hub "$HUB_URL" --format json | jq -re '.id')"
  fi
  scion service-accounts verify "$sa_id" "${sa_proj_flags[@]}" --hub "$HUB_URL" --format json | jq -e '.verified == true' >/dev/null
  echo "VERIFIED SA: $label ($sa_email)"
}

ensure_kaizen_schedule() {
  local pack_prefix="$1" kz_enabled="$2" kz_cron="$3" kz_tz="$4" kz_coord="$5" kz_gcp_obs="${6:-false}"
  if [[ "$kz_enabled" != "true" ]]; then
    echo "KAIZEN SCHEDULE: explicitly disabled via .factory/hub-project.yaml (kaizen.enabled=false)."
    return 0
  fi
  local sched_json existing_sched kz_sa_hint="worker SA"
  if [[ "$kz_gcp_obs" == "true" ]]; then
    kz_sa_hint="kaizen-viewer SA"
  fi
  sched_json="$(scion --format json schedule list --show recurring "${PROJ_FLAGS[@]}" --hub "$HUB_URL")"
  existing_sched="$(jq -r '((if type == "array" then . elif (.schedules | type) == "object" then (.schedules.schedules // []) elif (.schedules | type) == "array" then .schedules else (.items // []) end)[] | select(.name == "weekly-kaizen") | .id) // empty' <<< "$sched_json" | head -n 1)"
  if [[ -n "$existing_sched" ]]; then
    echo "SKIP schedule: weekly-kaizen ($existing_sched) already registered."
    return 0
  fi
  scion schedule create-recurring \
    --name "weekly-kaizen" \
    --cron "$kz_cron" \
    --time-zone "$kz_tz" \
    --type message \
    --agent "$kz_coord" \
    --wake \
    --message "Run weekly closed-loop Kaizen cycle: spawn ${pack_prefix}-kaizen-analyst (--role baseline, ${kz_sa_hint}), collect 0-token telemetry, publish report and Artifact, then retire it." \
    "${PROJ_FLAGS[@]}" \
    --hub "$HUB_URL"
  echo "SCHEDULED KAIZEN: weekly-kaizen (${kz_cron} ${kz_tz} -> ${kz_coord} --wake)"
}

ensure_coordinator_started() {
  local pack_prefix="$1" default_harness="$2" repo_cfg="$3" worker_sa="$4"
  local coord_name coord_tpl coord_harness coord_model coord_thinking disabled_json coord_disabled
  coord_name="$(jq -re --arg p "$pack_prefix" '.kaizen.coordinator_agent // ($p + "-coordinator")' <<< "$repo_cfg")"
  coord_tpl="${pack_prefix}-coordinator"
  coord_harness="$(jq -r --arg d "$default_harness" '.model_routing.coordinator.harness // $d' <<< "$repo_cfg")"
  coord_harness="${pack_prefix}-${coord_harness}"
  coord_model="$(jq -r '.model_routing.coordinator.model // empty' <<< "$repo_cfg")"
  coord_thinking="$(jq -r '.model_routing.coordinator.thinking_level // empty' <<< "$repo_cfg")"
  disabled_json="$(jq -c '.roster.disabled_roles // []' <<< "$repo_cfg")"
  coord_disabled="$(jq -r --arg full "$coord_tpl" 'index("coordinator") != null or index($full) != null' <<< "$disabled_json")"

  if [[ "$coord_disabled" == "true" ]]; then
    echo "SKIP coordinator start: coordinator role is disabled in roster.disabled_roles."
    return 0
  fi

  # Never pass -w <monorepo.subdir> on coordinator start (C1): keep full repo mounted so
  # .factory/ and AGENTS.md stay readable, and rely on coordinator-bootstrap-brief.md for subdir scope.
  local start_args=(start "$coord_name" -t "$coord_tpl" --role full --harness-config "$coord_harness")
  if [[ -n "$coord_model" ]]; then
    start_args+=(--model "$coord_model")
  fi
  if [[ -n "$coord_thinking" ]]; then
    start_args+=(--thinking-level "$coord_thinking")
  fi
  if [[ -n "$worker_sa" ]]; then
    start_args+=(--service-account "$worker_sa")
  fi
  local has_brief="false"
  if [[ -n "$TARGET_REPO" && -f "$TARGET_REPO/.factory/coordinator-bootstrap-brief.md" ]]; then
    has_brief="true"
    start_args+=(--task-file "$TARGET_REPO/.factory/coordinator-bootstrap-brief.md")
  else
    start_args+=("Read .factory/hub-project.yaml, .factory/knowledge-index.yaml, and .factory/waves/wave-1.yaml. Post a concise standby readiness summary in Scion Chat and run sciontool status blocked until the Product Owner approves execution.")
  fi
  start_args+=(--wait-timeout 2m --non-interactive ${PROJ_FLAGS[@]+"${PROJ_FLAGS[@]}"} --hub "$HUB_URL")

  # Auto-start only on v0.6.0+ repos with a standby brief (or explicit --start-coordinator),
  # preventing unexpected agent spawns when re-applying legacy v0.5.0 repos (H3).
  if [[ "$START_COORDINATOR" == "false" || -z "$TARGET_REPO" || ( "$START_COORDINATOR" == "auto" && "$has_brief" != "true" ) ]]; then
    echo "COORDINATOR START SKIPPED (opt-out, no --repo, or legacy repo without .factory/coordinator-bootstrap-brief.md). Ready command:"
    printf '  scion'
    printf ' %q' "${start_args[@]}"
    printf '\n'
    return 0
  fi

  # Fail-closed idempotency check (H2): never spawn a duplicate if scion list fails or returns non-JSON.
  local list_json list_rc=0 existing_coord
  list_json="$(scion --format json list ${PROJ_FLAGS[@]+"${PROJ_FLAGS[@]}"} --hub "$HUB_URL" 2>/dev/null)" || list_rc=$?
  if [[ "$list_rc" -ne 0 ]] || ! jq -e 'type == "array" or type == "object"' <<< "$list_json" >/dev/null 2>&1; then
    echo "WARNING: scion list failed or returned non-JSON (rc=${list_rc}). Skipping automatic coordinator start to prevent duplicate spawns. Run manually:" >&2
    printf '  scion' >&2
    printf ' %q' "${start_args[@]}" >&2
    printf '\n' >&2
    return 0
  fi

  existing_coord="$(jq -r \
    --arg n "$coord_name" \
    --arg pid "${SCION_HUB_PROJECT_ID:-}" \
    --arg pslug "${PROJECT_SLUG:-}" \
    '((if type == "array" then . else (.agents // .items // []) end)[]
      | select((.name == $n or .slug == $n)
        and (
          ($pid == "" and $pslug == "")
          or ((.projectId // .project_id // .projectSlug // .project_slug // .project // "") == "")
          or ($pid != "" and (.projectId // .project_id // .project // "") == $pid)
          or ($pslug != "" and (.projectSlug // .project_slug // .project // "") == $pslug)
        ))
      | .name // .slug) // empty' <<< "$list_json" | head -n 1 || true)"
  if [[ -n "$existing_coord" ]]; then
    echo "SKIP coordinator start: ${coord_name} already exists on Hub."
    return 0
  fi

  scion "${start_args[@]}"
  echo "COORDINATOR STARTED (standby mode): ${coord_name} (template=${coord_tpl}, harness=${coord_harness})"
}

do_apply() {
  do_preflight
  local pack_name pack_prefix repo_cfg mode max_dur max_turns max_calls auto_susp exclude_json
  pack_name="$(jq -re '.pack' "$KIT_DIR/manifest.json")"
  pack_prefix="$(jq -re '.pack_prefix // .pack' "$KIT_DIR/manifest.json")"
  repo_cfg="$(parse_repo_cfg "$pack_name")"

  mode="$(jq -re '.mode' <<< "$repo_cfg")"
  max_dur="$(jq -re '.limits.default_max_duration' <<< "$repo_cfg")"
  max_turns="$(jq -re '.limits.default_max_turns' <<< "$repo_cfg")"
  max_calls="$(jq -re '.limits.default_max_model_calls // 150' <<< "$repo_cfg")"
  auto_susp="$(jq -re '.limits.auto_suspend_idle' <<< "$repo_cfg")"
  exclude_json="$(jq -c '.exclude_skills' <<< "$repo_cfg")"

  do_backup

  # 1. Publish pack skills first and attach non-excluded project skills pinned to exact versions.
  # Handle concurrent shared-Hub 409 conflicts idempotently when multiple factories apply simultaneously (HC-09 F1).
  local existing_skills_json
  existing_skills_json="$(scion --format json project skills list "${PROJ_FLAGS[@]}" --hub "$HUB_URL")"
  while IFS=$'\t' read -r sname sver sattach; do
    [[ -n "$sname" ]] || continue
    local skill_dir="$KIT_DIR/skills/$sname"
    [[ -d "$skill_dir" ]] || continue
    if scion skills resolve "skill://scion/global/${sname}@${sver}" --hub "$HUB_URL" >/dev/null 2>&1; then
      echo "SKIP publish: ${sname}@${sver} already published in Hub Skill Bank."
    else
      local pub_out="" pub_rc=0
      pub_out="$(scion skills publish "$skill_dir" --scope global --version "$sver" --hub "$HUB_URL" 2>&1)" || pub_rc=$?
      if [[ "$pub_rc" -eq 0 ]]; then
        printf '%s\n' "$pub_out"
      elif grep -qiE '409|conflict|already exists|already published' <<< "$pub_out"; then
        local resolved_after="false"
        for _try in 1 2 3 4 5; do
          if scion skills resolve "skill://scion/global/${sname}@${sver}" --hub "$HUB_URL" >/dev/null 2>&1; then
            resolved_after="true"
            break
          fi
          sleep 1
        done
        if [[ "$resolved_after" == "true" ]]; then
          echo "SKIP publish (concurrent peer published ${sname}@${sver})."
        else
          printf '%s\n' "$pub_out" >&2
          return "$pub_rc"
        fi
      else
        printf '%s\n' "$pub_out" >&2
        return "$pub_rc"
      fi
    fi
    local is_excluded
    is_excluded="$(jq -r --arg n "$sname" 'index($n) != null' <<< "$exclude_json")"
    if [[ "$sattach" == "true" && "$is_excluded" != "true" ]]; then
      if ! jq -e --arg n "$sname" '(if type == "array" then . else (.entries // .skills // .items // []) end) | any(. == $n or (.name? == $n) or (.skillName? == $n) or (.skillSlug? == $n) or ((.uri? // .skillUri? // "") | contains("/" + $n)))' <<< "$existing_skills_json" >/dev/null 2>&1; then
        scion project skills add "skill://scion/global/${sname}@${sver}" "${PROJ_FLAGS[@]}" --hub "$HUB_URL"
      fi
    fi
  done < <(jq -r '.skills[] | [.name, .version, ((if has("attach_to_project") then .attach_to_project else true end) | tostring)] | @tsv' "$KIT_DIR/manifest.json")

  # 2. Materialize Vertex AI project/region + real harness image into global Scion harness-configs store and sync.
  local default_harness claude_mg_enabled gemini_loc claude_reg existing_hub inf_proj=""
  default_harness="$(jq -re '.harnesses.default // "antigravity-vertex"' <<< "$repo_cfg")"
  claude_mg_enabled="$(jq -re '(.harnesses.claude_model_garden_enabled // false) | tostring' <<< "$repo_cfg")"
  gemini_loc="$(jq -re '.harnesses.vertex_gemini_location // "global"' <<< "$repo_cfg")"
  claude_reg="$(jq -re '.harnesses.vertex_claude_region // "global"' <<< "$repo_cfg")"
  existing_hub="$(jq -r '(.existing_hub // false) | tostring' <<< "$repo_cfg")"
  if [[ -n "$LANDING_ZONE_JSON" && -f "$LANDING_ZONE_JSON" ]]; then
    inf_proj="$(jq -r '.inference_project_id.value // empty' "$LANDING_ZONE_JSON")"
  fi

  if [[ -d "$KIT_DIR/harness-configs" ]]; then
    local global_hc_root="${SCION_GLOBAL_DIR:-$HOME/.scion}/harness-configs"
    mkdir -p "$global_hc_root"
    for hc_dir in "$KIT_DIR"/harness-configs/*; do
      [[ -d "$hc_dir" && -f "$hc_dir/config.yaml" ]] || continue
      local hc_name img_override=""
      hc_name="$(basename "$hc_dir")"
      if [[ "$hc_name" == *"-claude-vertex" && "$claude_mg_enabled" != "true" ]]; then
        echo "SKIP harness-config: $hc_name (harnesses.claude_model_garden_enabled=false; using Vertex AI Gemini 1P)."
        continue
      fi
      if [[ "$hc_name" == *"-claude-vertex" ]]; then
        img_override="$HARNESS_IMAGE_CLAUDE"
        echo "VERTEX MODEL GARDEN CHECKPOINT: confirm claude-opus-5-5 is manually enabled at https://console.cloud.google.com/vertex-ai/publishers/anthropic/model-garden/claude-opus-5-5?project=${inf_proj:-YOUR_INFERENCE_PROJECT} (region=${claude_reg})."
      elif [[ "$hc_name" == *"-antigravity-vertex" ]]; then
        img_override="$HARNESS_IMAGE_ANTIGRAVITY"
      fi
      rm -rf "${global_hc_root:?}/${hc_name}"
      local base_harness base_yaml_args=()
      base_harness="$(python3 -c 'import sys, yaml; print((yaml.safe_load(open(sys.argv[1])) or {}).get("harness", ""))' "$hc_dir/config.yaml")"
      if [[ -n "$base_harness" ]] && scion harness-config pull "$base_harness" --to "${global_hc_root}/${hc_name}" --hub "$HUB_URL" >/dev/null 2>&1; then
        base_yaml_args=(--base-harness-yaml "${global_hc_root}/${hc_name}/config.yaml")
      else
        cp -r "$hc_dir" "${global_hc_root}/${hc_name}"
      fi
      python3 "$SCRIPT_DIR/parse_hub_project.py" \
        --render-harness-src "$hc_dir/config.yaml" \
        --render-harness-dst "${global_hc_root}/${hc_name}/config.yaml" \
        "${base_yaml_args[@]}" \
        --inference-project "$inf_proj" \
        --gemini-location "$gemini_loc" \
        --claude-region "$claude_reg" \
        --pin-image "$img_override"
      local hc_out="" hc_rc=0
      hc_out="$(scion harness-config sync "$hc_name" --global --hub "$HUB_URL" 2>&1)" || hc_rc=$?
      if [[ "$hc_rc" -eq 0 ]]; then
        printf '%s\n' "$hc_out"
      elif grep -qiE '409|conflict|already exists' <<< "$hc_out"; then
        sleep 2
        scion harness-config sync "$hc_name" --global --hub "$HUB_URL"
      else
        printf '%s\n' "$hc_out" >&2
        return "$hc_rc"
      fi
    done
    # Avoid overwriting Hub-global default_harness_config when attaching another factory to a shared Hub (HC-09 F1).
    if [[ "$existing_hub" == "true" ]]; then
      echo "SKIP hub-global default_harness_config update (brownfield.existing_hub=true; agents pass --harness-config explicitly)."
    else
      scion hub settings set default_harness_config "${pack_prefix}-${default_harness}" --hub "$HUB_URL"
    fi
  fi

  # 3. Sync local templates filtered by roster.disabled_roles (zero upstream source URL).
  local disabled_roles_json
  disabled_roles_json="$(jq -c '.roster.disabled_roles // []' <<< "$repo_cfg")"
  for tpl_dir in "$KIT_DIR"/templates/*; do
    [[ -d "$tpl_dir" ]] || continue
    local tname role_short is_disabled
    tname="$(basename "$tpl_dir")"
    role_short="${tname#"${pack_prefix}-"}"
    is_disabled="$(jq -r --arg full "$tname" --arg short "$role_short" 'index($full) != null or index($short) != null' <<< "$disabled_roles_json")"
    if [[ "$is_disabled" == "true" ]]; then
      echo "SKIP template (disabled in roster): $tname"
      continue
    fi
    scion templates sync "$tpl_dir" --name "$tname" "${PROJ_FLAGS[@]}" --hub "$HUB_URL"
  done

  # 4. Register and verify factory SAs idempotently (never register sandbox_janitor on the Hub).
  local resolved_proj_id coord_sa="" worker_sa="" deploy_target
  deploy_target="$(jq -r '.deploy_target // ""' <<< "$repo_cfg")"
  resolved_proj_id="$(resolve_project_id)"
  if [[ -n "$resolved_proj_id" ]]; then
    export SCION_HUB_PROJECT_ID="$resolved_proj_id"
  fi
  if [[ -n "$LANDING_ZONE_JSON" ]]; then
    local inf_p sbx_p dep_sa eval_sa
    inf_p="$(jq -re '.inference_project_id.value' "$LANDING_ZONE_JSON")"
    sbx_p="$(jq -r '.sandbox_project_id.value // empty' "$LANDING_ZONE_JSON")"
    coord_sa="$(jq -r '.coordinator_sa_email.value // empty' "$LANDING_ZONE_JSON")"
    worker_sa="$(jq -re '.worker_sa_email.value' "$LANDING_ZONE_JSON")"
    dep_sa="$(jq -r '.sandbox_deployer_sa_email.value // empty' "$LANDING_ZONE_JSON")"
    eval_sa="$(jq -r '.sandbox_evaluator_sa_email.value // empty' "$LANDING_ZONE_JSON")"

    local id_proj_flags=("${PROJ_FLAGS[@]}")
    if [[ -n "${SCION_HUB_PROJECT_ID:-}" ]]; then
      id_proj_flags=()
    fi
    if [[ -n "$coord_sa" ]]; then
      register_and_verify_sa "$coord_sa" "$inf_p" "factory-coordinator"
    fi
    register_and_verify_sa "$worker_sa" "$inf_p" "factory-worker"
    scion project identity default set "$worker_sa" "${id_proj_flags[@]}" --hub "$HUB_URL"

    if [[ "$mode" == "sandbox-direct" && "$deploy_target" != "none" ]]; then
      [[ -n "$sbx_p" && -n "$dep_sa" ]] || {
        echo "APPLY FAILED: sandbox-direct with deploy_target='${deploy_target:-default}' requires sandbox_project_id and sandbox_deployer_sa_email in landing-zone outputs." >&2
        exit 1
      }
      register_and_verify_sa "$dep_sa" "$sbx_p" "${pack_prefix}-deployer"
      if [[ -n "$eval_sa" ]]; then
        register_and_verify_sa "$eval_sa" "$sbx_p" "${pack_prefix}-evaluator"
      elif [[ "$pack_name" != "generic" ]]; then
        echo "APPLY FAILED: pack '${pack_name}' in sandbox-direct mode requires sandbox_evaluator_sa_email." >&2
        exit 1
      fi
    else
      echo "SKIP Sandbox Deployer/Evaluator SA registration (mode=${mode}, deploy_target=${deploy_target:-default})."
    fi

    # Register read-only Tier-B Kaizen Viewer SA on Hub when enable_gcp_obs is active (HC-04 F5).
    local kz_gcp_obs kaizen_sa
    kz_gcp_obs="$(jq -r '(.kaizen.enable_gcp_obs // false) | tostring' <<< "$repo_cfg")"
    kaizen_sa="$(jq -r '.kaizen_viewer_sa_email.value // empty' "$LANDING_ZONE_JSON")"
    if [[ "$kz_gcp_obs" == "true" && -n "$kaizen_sa" ]]; then
      register_and_verify_sa "$kaizen_sa" "$inf_p" "kaizen-viewer"
    fi
  fi

  # 5. Apply security, Vertex AI project env, and FinOps settings last.
  # Note: default_agent_role is read-only through the Scion v0.4 server-config API
  # (dbUnwrittenLayer1Paths) and is enforced per template and via Stage 02 settings.yaml.
  # Use gcp_iam_deny_unknown_policy=fail-open (while keeping gcp_iam_check_mode=enforce) so
  # project-scoped Hub SAs pass Policy Troubleshooter Allow checks without org-level denyReviewer (HC-01 F17b).
  scion hub settings set server.hub.gcp_iam_check_mode enforce --hub "$HUB_URL"
  scion hub settings set server.hub.gcp_iam_deny_unknown_policy "${GCP_IAM_DENY_UNKNOWN_POLICY:-fail-open}" --hub "$HUB_URL"
  scion hub settings set default_gcp_identity_mode block --hub "$HUB_URL"
  scion hub settings set default_max_duration "$max_dur" --hub "$HUB_URL"
  scion hub settings set default_max_turns "$max_turns" --hub "$HUB_URL"
  scion hub settings set default_max_model_calls "$max_calls" --hub "$HUB_URL"
  scion hub settings set server.hub.auto_suspend_idle "$auto_susp" --hub "$HUB_URL"

  # Set project-scope Vertex AI env vars (injectionMode=always) so container-side harness provisioners
  # (e.g. antigravity/provision.py) and ADC quotaProject routing receive inference_project_id on both
  # Lite VM and GKE cross-project topologies (HC-01 F24, HC-02 F8).
  if [[ -n "$inf_proj" && -n "${SCION_HUB_TOKEN:-}" ]]; then
    local proj_id="${resolved_proj_id:-}"
    if [[ -z "$proj_id" && -n "$PROJECT_SLUG" ]]; then
      proj_id="$(resolve_project_id)"
    fi
    if [[ -n "$proj_id" ]]; then
      local kv k v
      for kv in "GOOGLE_CLOUD_PROJECT=${inf_proj}" "GOOGLE_CLOUD_QUOTA_PROJECT=${inf_proj}" "GOOGLE_CLOUD_LOCATION=${gemini_loc}" "GOOGLE_GENAI_USE_VERTEXAI=true" "AGY_ADC_AUTH=true"; do
        k="${kv%%=*}"; v="${kv#*=}"
        curl -sf -X PUT \
          -H "Authorization: Bearer ${SCION_HUB_TOKEN}" \
          -H "Content-Type: application/json" \
          "${HUB_URL%/}/api/v1/projects/${proj_id}/env/${k}" \
          -d "{\"value\":\"${v}\",\"injectionMode\":\"always\"}" >/dev/null \
          && echo "SET PROJECT ENV: ${k}=${v}" || true
      done
      warn_github_token_injection_mode "$proj_id"
    fi
  fi

  # 6. Schedule weekly closed-loop Kaizen by default on every project.
  ensure_kaizen_schedule \
    "$pack_prefix" \
    "$(jq -re '.kaizen.enabled | tostring' <<< "$repo_cfg")" \
    "$(jq -re '.kaizen.schedule_cron' <<< "$repo_cfg")" \
    "$(jq -re '.kaizen.time_zone' <<< "$repo_cfg")" \
    "$(jq -re '.kaizen.coordinator_agent' <<< "$repo_cfg")" \
    "$(jq -r '(.kaizen.enable_gcp_obs // false) | tostring' <<< "$repo_cfg")"

  if [[ -n "$TARGET_REPO" ]]; then
    do_overlay_sync
  fi
  ensure_coordinator_started "$pack_prefix" "$default_harness" "$repo_cfg" "${coord_sa:-$worker_sa}"
  warn_adk_ge_license_preflight "$pack_name"
  print_github_ci_variables "$pack_name"
  echo "APPLY COMPLETE."
}

do_overlay_sync() {
  [[ -n "$TARGET_REPO" ]] || { echo "--repo is required for overlay-sync" >&2; exit 2; }
  local pack_name repo_cfg pack_skills_json proj_id existing_skills_json count=0
  pack_name="$(jq -re '.pack' "$KIT_DIR/manifest.json")"
  pack_skills_json="$(jq -c '[.skills[].name]' "$KIT_DIR/manifest.json")"
  repo_cfg="$(parse_repo_cfg "$pack_name")"

  # Scion v0.4 requires the Hub project UUID in project-scoped skill URIs:
  # skill://scion/project/<project_id>/<name>@<version> (HC-03 F2).
  proj_id="$(resolve_project_id)"
  if [[ -n "$proj_id" ]]; then
    export SCION_HUB_PROJECT_ID="$proj_id"
  fi
  local ov_proj_flags=("${PROJ_FLAGS[@]}")
  if [[ -n "${SCION_HUB_PROJECT_ID:-}" ]]; then
    ov_proj_flags=()
  fi
  existing_skills_json="$(scion --format json project skills list "${ov_proj_flags[@]}" --hub "$HUB_URL" 2>/dev/null || echo '[]')"

  while IFS=$'\t' read -r rel_dir sver; do
    [[ -n "$rel_dir" ]] || continue
    local sdir="$TARGET_REPO/$rel_dir"
    [[ -d "$sdir" ]] || { echo "Missing declared overlay skill directory: $sdir" >&2; exit 1; }
    python3 "$SCRIPT_DIR/parse_hub_project.py" \
      --check-overlay-skill "$sdir" \
      --pack-skills-json "$pack_skills_json"
    local sname uri
    sname="$(basename "$sdir")"
    if [[ -n "$proj_id" ]]; then
      uri="skill://scion/project/${proj_id}/${sname}@${sver}"
    else
      uri="skill://scion/project/${sname}@${sver}"
    fi
    if scion skills resolve "$uri" --hub "$HUB_URL" >/dev/null 2>&1; then
      echo "SKIP overlay publish: ${sname}@${sver} already published."
    else
      scion skills publish "$sdir" --scope project --version "$sver" "${ov_proj_flags[@]}" --hub "$HUB_URL"
    fi
    if ! jq -e --arg u "$uri" --arg n "$sname" '(if type == "array" then . else (.entries // .skills // .items // []) end) | any((.skillUri? // .uri? // "") == $u or (.skillName? // .name? // "") == $n)' <<< "$existing_skills_json" >/dev/null 2>&1; then
      scion project skills add "$uri" "${ov_proj_flags[@]}" --hub "$HUB_URL"
    else
      echo "SKIP overlay attach: ${uri} already attached."
    fi
    count=$((count + 1))
  done < <(jq -r '.overlay_skills[] | [.dir, .version] | @tsv' <<< "$repo_cfg")

  echo "OVERLAY SYNC COMPLETE (skills_synced=$count)."
}

do_rollback() {
  [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR/templates" ]] || { echo "--backup-dir is required for rollback" >&2; exit 2; }
  local restored=0
  for tpl_dir in "$BACKUP_DIR"/templates/*; do
    [[ -d "$tpl_dir" ]] || continue
    local tname
    tname="$(basename "$tpl_dir")"
    scion templates sync "$tpl_dir" --name "$tname" "${PROJ_FLAGS[@]}" --hub "$HUB_URL"
    restored=$((restored + 1))
  done
  if [[ "$restored" -eq 0 ]]; then
    echo "ROLLBACK FAILED: backup at $BACKUP_DIR contains 0 backed-up templates (first-install backup cannot roll back automatically)." >&2
    exit 1
  fi
  echo "ROLLBACK COMPLETE from $BACKUP_DIR (templates_restored=$restored)."
}

case "$ACTION" in
  preflight) do_preflight ;;
  plan) do_plan ;;
  backup) do_backup ;;
  apply) do_apply ;;
  overlay-sync) do_overlay_sync ;;
  rollback) do_rollback ;;
  *) usage ;;
esac
