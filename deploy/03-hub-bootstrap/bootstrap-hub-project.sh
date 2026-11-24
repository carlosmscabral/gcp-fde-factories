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
  [--harness-image-antigravity <digest-or-registry-ref>] [--harness-image-claude <digest-or-registry-ref>]
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
{"pack":"","mode":"sandbox-direct","diversity_profile":"cross-model","limits":{"default_max_duration":"2h","default_max_turns":60,"default_max_model_calls":150,"auto_suspend_idle":true},"exclude_skills":[],"overlay_skills":[],"kaizen":{"enabled":true,"schedule_cron":"0 17 * * 5","time_zone":"America/Sao_Paulo","coordinator_agent":"coordinator","enable_gcp_obs":false},"harnesses":{"default":"antigravity-vertex","claude_model_garden_enabled":false,"vertex_gemini_location":"global","vertex_claude_region":"global"},"model_routing":{}}
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
  echo "=== PLAN: Pack Templates (Prefix-Scoped Only) ==="
  ls -1 "$KIT_DIR/templates"
  echo "=== PLAN: Hub Skill Bank Skills ==="
  ls -1 "$KIT_DIR/skills"
  if [[ -d "$KIT_DIR/harness-configs" ]]; then
    echo "=== PLAN: Harness Configs ==="
    ls -1 "$KIT_DIR/harness-configs"
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

register_and_verify_sa() {
  local sa_email="$1" project_id="$2" label="$3"
  local sa_list_json existing_id sa_id
  sa_list_json="$(scion --format json service-accounts list "${PROJ_FLAGS[@]}" --hub "$HUB_URL")"
  existing_id="$(jq -r --arg email "$sa_email" '((if type == "array" then . else (.serviceAccounts // .items // []) end)[] | select(.email == $email) | .id) // empty' <<< "$sa_list_json" | head -n 1)"
  if [[ -n "$existing_id" ]]; then
    sa_id="$existing_id"
    echo "EXISTING SA: $label ($sa_email -> $sa_id)"
  else
    sa_id="$(scion service-accounts add "$sa_email" --gcp-project "$project_id" --name "$label" "${PROJ_FLAGS[@]}" --hub "$HUB_URL" --format json | jq -re '.id')"
  fi
  scion service-accounts verify "$sa_id" "${PROJ_FLAGS[@]}" --hub "$HUB_URL" --format json | jq -e '.verified == true' >/dev/null
  echo "VERIFIED SA: $label ($sa_email)"
}

ensure_kaizen_schedule() {
  local pack_prefix="$1" kz_enabled="$2" kz_cron="$3" kz_tz="$4" kz_coord="$5"
  if [[ "$kz_enabled" != "true" ]]; then
    echo "KAIZEN SCHEDULE: explicitly disabled via .factory/hub-project.yaml (kaizen.enabled=false)."
    return 0
  fi
  local sched_json existing_sched
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
    --message "Run weekly closed-loop Kaizen cycle: spawn ${pack_prefix}-kaizen-analyst (--role baseline, worker SA), collect 0-token telemetry, publish report and Artifact, then retire it." \
    "${PROJ_FLAGS[@]}" \
    --hub "$HUB_URL"
  echo "SCHEDULED KAIZEN: weekly-kaizen (${kz_cron} ${kz_tz} -> ${kz_coord} --wake)"
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
  local existing_skills_json
  existing_skills_json="$(scion --format json project skills list "${PROJ_FLAGS[@]}" --hub "$HUB_URL")"
  while IFS=$'\t' read -r sname sver sattach; do
    [[ -n "$sname" ]] || continue
    local skill_dir="$KIT_DIR/skills/$sname"
    [[ -d "$skill_dir" ]] || continue
    if scion skills resolve "skill://scion/global/${sname}@${sver}" --hub "$HUB_URL" >/dev/null 2>&1; then
      echo "SKIP publish: ${sname}@${sver} already published in Hub Skill Bank."
    else
      scion skills publish "$skill_dir" --scope global --version "$sver" --hub "$HUB_URL"
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
  local default_harness claude_mg_enabled gemini_loc claude_reg inf_proj=""
  default_harness="$(jq -re '.harnesses.default // "antigravity-vertex"' <<< "$repo_cfg")"
  claude_mg_enabled="$(jq -re '(.harnesses.claude_model_garden_enabled // false) | tostring' <<< "$repo_cfg")"
  gemini_loc="$(jq -re '.harnesses.vertex_gemini_location // "global"' <<< "$repo_cfg")"
  claude_reg="$(jq -re '.harnesses.vertex_claude_region // "global"' <<< "$repo_cfg")"
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
      scion harness-config sync "$hc_name" --global --hub "$HUB_URL"
    done
    scion hub settings set default_harness_config "${pack_prefix}-${default_harness}" --hub "$HUB_URL"
  fi

  # 3. Sync local templates (stores zero upstream source URL, blocking Refresh clobber).
  for tpl_dir in "$KIT_DIR"/templates/*; do
    [[ -d "$tpl_dir" ]] || continue
    local tname
    tname="$(basename "$tpl_dir")"
    scion templates sync "$tpl_dir" --name "$tname" "${PROJ_FLAGS[@]}" --hub "$HUB_URL"
  done

  # 4. Register and verify factory SAs idempotently (never register sandbox_janitor on the Hub).
  if [[ -n "$LANDING_ZONE_JSON" ]]; then
    local inf_p sbx_p worker_sa dep_sa eval_sa
    inf_p="$(jq -re '.inference_project_id.value' "$LANDING_ZONE_JSON")"
    sbx_p="$(jq -re '.sandbox_project_id.value' "$LANDING_ZONE_JSON")"
    worker_sa="$(jq -re '.worker_sa_email.value' "$LANDING_ZONE_JSON")"
    dep_sa="$(jq -re '.sandbox_deployer_sa_email.value' "$LANDING_ZONE_JSON")"
    eval_sa="$(jq -re '.sandbox_evaluator_sa_email.value' "$LANDING_ZONE_JSON")"

    register_and_verify_sa "$worker_sa" "$inf_p" "factory-worker"
    scion project identity default set "$worker_sa" "${PROJ_FLAGS[@]}" --hub "$HUB_URL"

    if [[ "$mode" == "sandbox-direct" ]]; then
      register_and_verify_sa "$dep_sa" "$sbx_p" "${pack_prefix}-deployer"
      register_and_verify_sa "$eval_sa" "$sbx_p" "${pack_prefix}-evaluator"
    else
      echo "MODE ci-only: skipping Sandbox Deployer and Evaluator SA registration on Hub."
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
  # (e.g. antigravity/provision.py) receive GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION in
  # auth-candidates.json (HC-01 F24).
  if [[ -n "$inf_proj" && -n "${SCION_HUB_TOKEN:-}" && -n "$PROJECT_SLUG" ]]; then
    local proj_id
    proj_id="$(curl -sf -H "Authorization: Bearer ${SCION_HUB_TOKEN}" "${HUB_URL%/}/api/v1/projects" \
      | jq -r --arg s "$PROJECT_SLUG" '((if type == "array" then . else (.projects // .items // []) end)[] | select(.slug == $s or .name == $s) | .id) // empty' | head -n 1 || true)"
    if [[ -n "$proj_id" ]]; then
      local kv k v
      for kv in "GOOGLE_CLOUD_PROJECT=${inf_proj}" "GOOGLE_CLOUD_LOCATION=${gemini_loc}" "GOOGLE_GENAI_USE_VERTEXAI=true"; do
        k="${kv%%=*}"; v="${kv#*=}"
        curl -sf -X PUT \
          -H "Authorization: Bearer ${SCION_HUB_TOKEN}" \
          -H "Content-Type: application/json" \
          "${HUB_URL%/}/api/v1/projects/${proj_id}/env/${k}" \
          -d "{\"value\":\"${v}\",\"injectionMode\":\"always\"}" >/dev/null \
          && echo "SET PROJECT ENV: ${k}=${v}" || true
      done
    fi
  fi

  # 6. Schedule weekly closed-loop Kaizen by default on every project.
  ensure_kaizen_schedule \
    "$pack_prefix" \
    "$(jq -re '.kaizen.enabled | tostring' <<< "$repo_cfg")" \
    "$(jq -re '.kaizen.schedule_cron' <<< "$repo_cfg")" \
    "$(jq -re '.kaizen.time_zone' <<< "$repo_cfg")" \
    "$(jq -re '.kaizen.coordinator_agent' <<< "$repo_cfg")"

  if [[ -n "$TARGET_REPO" ]]; then
    do_overlay_sync
  fi
  echo "APPLY COMPLETE."
}

do_overlay_sync() {
  [[ -n "$TARGET_REPO" ]] || { echo "--repo is required for overlay-sync" >&2; exit 2; }
  local pack_name repo_cfg pack_skills_json count=0
  pack_name="$(jq -re '.pack' "$KIT_DIR/manifest.json")"
  pack_skills_json="$(jq -c '[.skills[].name]' "$KIT_DIR/manifest.json")"
  repo_cfg="$(parse_repo_cfg "$pack_name")"

  while IFS=$'\t' read -r rel_dir sver; do
    [[ -n "$rel_dir" ]] || continue
    local sdir="$TARGET_REPO/$rel_dir"
    [[ -d "$sdir" ]] || { echo "Missing declared overlay skill directory: $sdir" >&2; exit 1; }
    python3 "$SCRIPT_DIR/parse_hub_project.py" \
      --check-overlay-skill "$sdir" \
      --pack-skills-json "$pack_skills_json"
    local sname
    sname="$(basename "$sdir")"
    if scion skills resolve "skill://scion/project/${sname}@${sver}" --hub "$HUB_URL" >/dev/null 2>&1; then
      echo "SKIP overlay publish: ${sname}@${sver} already published."
    else
      scion skills publish "$sdir" --scope project --version "$sver" --hub "$HUB_URL"
    fi
    scion project skills add "skill://scion/project/${sname}@${sver}" --hub "$HUB_URL"
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
    scion templates sync "$tpl_dir" --name "$tname" --hub "$HUB_URL"
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
