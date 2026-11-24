#!/usr/bin/env bash
# Stage 03 Hub Bootstrap reconciler (Contract 2: preflight / plan / backup / apply / rollback / overlay-sync).
# Enforces compat.yaml closed version checks and Spike-validated Scion v0.4.0-preview.3 fail-closed settings.
# Customer principal runs this script so coordinator ownership belongs to the customer from Day 1.
set -euo pipefail

ACTION="${1:-}"
KIT_DIR=""
LANDING_ZONE_JSON=""
HUB_URL=""
TARGET_REPO=""
BACKUP_DIR=""

usage() {
  cat <<'EOF'
Usage: bootstrap-hub-project.sh <preflight|plan|backup|apply|rollback|overlay-sync> \
  --kit <release-kit-dir> --hub <https-or-loopback-url> \
  [--landing-zone <landing-zone-outputs.json>] [--repo <target-repo-dir>] [--backup-dir <dir>]
EOF
  exit 2
}

shift || usage
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kit) KIT_DIR="$2"; shift 2 ;;
    --hub) HUB_URL="$2"; shift 2 ;;
    --landing-zone) LANDING_ZONE_JSON="$2"; shift 2 ;;
    --repo) TARGET_REPO="$2"; shift 2 ;;
    --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; usage ;;
  esac
done

[[ -n "$KIT_DIR" && -n "$HUB_URL" ]] || usage
export SCION_HUB_ENDPOINT="$HUB_URL"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required CLI: $1" >&2; exit 1; }
}

do_preflight() {
  require_cmd scion
  require_cmd jq
  local version_out tested_list
  version_out="$(scion version 2>&1 | grep -Eo 'v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?' | head -n 1 || true)"
  tested_list="$(jq -r '.scion_tested[]' "$KIT_DIR/manifest.json")"
  if ! grep -Fxq "$version_out" <<< "$tested_list"; then
    echo "PREFLIGHT FAILED: Scion version '${version_out:-unknown}' is not in compat.yaml closed tested list." >&2
    exit 1
  fi
  echo "PREFLIGHT OK: Scion $version_out matched compat.yaml tested list."
  scion hub status --hub "$HUB_URL"
}

do_plan() {
  do_preflight
  echo "=== PLAN: Pack Templates (Prefix-Scoped Only) ==="
  ls -1 "$KIT_DIR/templates"
  echo "=== PLAN: Hub Skill Bank Skills ==="
  ls -1 "$KIT_DIR/skills"
  echo "=== PLAN: Current Hub Template Status ==="
  scion templates status --hub "$HUB_URL" || true
}

do_backup() {
  local ts dir
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  dir="${BACKUP_DIR:-.backups/$ts}"
  mkdir -p "$dir/templates"
  echo "=== BACKUP: Exporting Hub settings and templates to $dir ==="
  scion hub settings get --section gcp_iam --hub "$HUB_URL" > "$dir/gcp_iam.txt" || true
  scion hub settings get --section agent_defaults --hub "$HUB_URL" > "$dir/agent_defaults.txt" || true
  scion templates list --hub "$HUB_URL" > "$dir/templates_list.txt" || true
  for tpl_dir in "$KIT_DIR"/templates/*; do
    local name
    name="$(basename "$tpl_dir")"
    scion templates pull "$name" --to "$dir/templates/$name" 2>/dev/null || true
  done
  echo "BACKUP COMPLETE: $dir"
}

register_and_verify_sa() {
  local sa_email="$1" project_id="$2" label="$3"
  local sa_id
  sa_id="$(scion service-accounts add "$sa_email" --gcp-project "$project_id" --name "$label" --hub "$HUB_URL" --format json | jq -r '.id')"
  scion service-accounts verify "$sa_id" --hub "$HUB_URL" --format json | jq -e '.verified == true' >/dev/null
  echo "VERIFIED SA: $label ($sa_email)"
}

do_apply() {
  do_preflight
  do_backup

  # Enforce Spike-validated Scion v0.4.0-preview.3 security and FinOps defaults.
  scion hub settings set server.hub.gcp_iam_check_mode enforce --hub "$HUB_URL"
  scion hub settings set server.hub.gcp_iam_deny_unknown_policy fail-closed --hub "$HUB_URL"
  scion hub settings set default_gcp_identity_mode block --hub "$HUB_URL"
  scion hub settings set default_max_duration 2h --hub "$HUB_URL"
  scion hub settings set default_max_turns 60 --hub "$HUB_URL"
  scion hub settings set server.hub.auto_suspend_idle true --hub "$HUB_URL"

  # Register and verify factory SAs (never register sandbox_janitor on the Hub).
  if [[ -n "$LANDING_ZONE_JSON" ]]; then
    local hub_p inf_p sbx_p worker_sa dep_sa eval_sa mode
    hub_p="$(jq -r '.hub_project_id.value' "$LANDING_ZONE_JSON")"
    inf_p="$(jq -r '.inference_project_id.value' "$LANDING_ZONE_JSON")"
    sbx_p="$(jq -r '.sandbox_project_id.value' "$LANDING_ZONE_JSON")"
    worker_sa="$(jq -r '.worker_sa_email.value' "$LANDING_ZONE_JSON")"
    dep_sa="$(jq -r '.sandbox_deployer_sa_email.value' "$LANDING_ZONE_JSON")"
    eval_sa="$(jq -r '.sandbox_evaluator_sa_email.value' "$LANDING_ZONE_JSON")"

    register_and_verify_sa "$worker_sa" "$inf_p" "factory-worker"
    scion project identity default set "$worker_sa" --hub "$HUB_URL"

    mode="sandbox-direct"
    if [[ -n "$TARGET_REPO" && -f "$TARGET_REPO/.factory/hub-project.yaml" ]]; then
      mode="$(grep -E '^mode:' "$TARGET_REPO/.factory/hub-project.yaml" | awk '{print $2}' | tr -d '\"' || echo sandbox-direct)"
    fi
    local pack_prefix
    pack_prefix="$(jq -r '.pack_prefix // .pack // "gecx"' "$KIT_DIR/manifest.json")"
    if [[ "$mode" == "sandbox-direct" ]]; then
      register_and_verify_sa "$dep_sa" "$sbx_p" "${pack_prefix}-deployer"
      register_and_verify_sa "$eval_sa" "$sbx_p" "${pack_prefix}-evaluator"
    else
      echo "MODE ci-only: skipping Sandbox Deployer and Evaluator SA registration on Hub."
    fi
  fi

  # Publish all pack and SEP skills to Hub Skill Bank (idempotent across already-published versions).
  # Attach only attach_to_project=true skills project-wide; role-specific SEP skills mount via template skills[].
  local existing_skills
  existing_skills="$(scion project skills list --hub "$HUB_URL" 2>/dev/null || true)"
  while IFS=$'\t' read -r sname sver sattach; do
    [[ -n "$sname" ]] || continue
    local skill_dir="$KIT_DIR/skills/$sname"
    [[ -d "$skill_dir" ]] || continue
    if scion skills resolve "skill://scion/global/${sname}@${sver}" --hub "$HUB_URL" >/dev/null 2>&1; then
      echo "SKIP publish: ${sname}@${sver} already published in Hub Skill Bank."
    else
      scion skills publish "$skill_dir" --scope global --version "$sver" --hub "$HUB_URL"
    fi
    if [[ "$sattach" == "true" ]]; then
      if ! grep -Fq "$sname" <<< "$existing_skills"; then
        scion project skills add "skill://scion/global/${sname}" --hub "$HUB_URL"
      fi
    fi
  done < <(jq -r '.skills[] | [.name, .version, ((if has("attach_to_project") then .attach_to_project else true end) | tostring)] | @tsv' "$KIT_DIR/manifest.json")

  # Sync local templates only (stores zero upstream source URL, blocking accidental Refresh clobber).
  for tpl_dir in "$KIT_DIR"/templates/*; do
    [[ -d "$tpl_dir" ]] || continue
    local tname
    tname="$(basename "$tpl_dir")"
    scion templates sync "$tpl_dir" --name "$tname" --hub "$HUB_URL"
  done

  if [[ -n "$TARGET_REPO" ]]; then
    do_overlay_sync
  fi
  echo "APPLY COMPLETE."
}

do_overlay_sync() {
  [[ -n "$TARGET_REPO" ]] || { echo "--repo is required for overlay-sync" >&2; exit 2; }
  local published=0
  if [[ -f "$TARGET_REPO/.factory/hub-project.yaml" ]] && command -v python3 >/dev/null 2>&1; then
    while IFS=$'\t' read -r rel_dir sver; do
      [[ -n "$rel_dir" ]] || continue
      local sdir="$TARGET_REPO/$rel_dir"
      [[ -d "$sdir" ]] || continue
      local sname
      sname="$(basename "$sdir")"
      scion skills publish "$sdir" --scope project --version "${sver:-1.0.0}" --hub "$HUB_URL"
      scion project skills add "skill://${sname}" --hub "$HUB_URL" || true
      published=1
    done < <(python3 -c '
import pathlib, sys, yaml
cfg = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
for item in cfg.get("overlay_skills", []):
    print(f"{item.get(\"dir\", \"\")}\t{item.get(\"version\", \"1.0.0\")}")
' "$TARGET_REPO/.factory/hub-project.yaml" 2>/dev/null || true)
  fi
  if [[ "$published" -eq 0 && -d "$TARGET_REPO/skills" ]]; then
    for sdir in "$TARGET_REPO"/skills/*; do
      [[ -d "$sdir" ]] || continue
      local sname
      sname="$(basename "$sdir")"
      scion skills publish "$sdir" --scope project --version "1.0.0" --hub "$HUB_URL"
      scion project skills add "skill://${sname}" --hub "$HUB_URL" || true
      published=1
    done
  fi
  if [[ "$published" -eq 0 ]]; then
    echo "No customer overlay skills/ directory found in $TARGET_REPO."
  fi
  if [[ -f "$TARGET_REPO/.factory/hub-project.yaml" ]] && grep -Eq '^[[:space:]]*enabled:[[:space:]]*true' "$TARGET_REPO/.factory/hub-project.yaml"; then
    local pack_prefix
    pack_prefix="$(jq -r '.pack_prefix // .pack // "gecx"' "$KIT_DIR/manifest.json")"
    echo "KAIZEN HINT: schedule weekly telemetry via scion schedule create-recurring --template ${pack_prefix}-kaizen-analyst --hub $HUB_URL"
  fi
  echo "OVERLAY SYNC COMPLETE."
}

do_rollback() {
  [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR/templates" ]] || { echo "--backup-dir is required for rollback" >&2; exit 2; }
  for tpl_dir in "$BACKUP_DIR"/templates/*; do
    [[ -d "$tpl_dir" ]] || continue
    local tname
    tname="$(basename "$tpl_dir")"
    scion templates sync "$tpl_dir" --name "$tname" --hub "$HUB_URL"
  done
  echo "ROLLBACK COMPLETE from $BACKUP_DIR."
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
