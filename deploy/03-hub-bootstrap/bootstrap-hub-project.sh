#!/usr/bin/env bash
# Stage 03 Hub Bootstrap reconciler (Contract 2: platform-init / preflight / plan / backup / apply / rollback / overlay-sync).
# Separates Phase A 1x Hub-global setup (platform-init) from Phase B N-factory onboarding (apply),
# enforces compat.yaml closed version checks, Scion v0.4.0-preview.4 CLI contracts, fail-closed
# image validation, isolated --network=none customer Dockerfile verification, sibling-safe Kaizen
# scheduling, and strict overlay skill budget + collision verification.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-}"
KIT_DIR=""
LANDING_ZONE_JSON=""
HUB_URL=""
PROJECT_SLUG=""
TARGET_REPO=""
CONFIG_PATH=""
GCLOUD_CONFIG=""
SKIP_CUSTOMER_IMAGE_BUILD="false"
ALLOW_HUB_CUSTOMER_IMAGE_BUILD="false"
HARNESS_IMAGE_TESTER=""
BACKUP_DIR=""
HARNESS_IMAGE_ANTIGRAVITY=""
HARNESS_IMAGE_CLAUDE=""
START_COORDINATOR="auto"
ALLOW_UNPUSHED_FACTORY="false"
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
Usage: bootstrap-hub-project.sh <platform-init|preflight|plan|backup|apply|rollback|overlay-sync> \
  --kit <release-kit-dir> --hub <https-or-loopback-url> \
  [--landing-zone <landing-zone-outputs.json>] [--repo <target-repo-dir>] [--config <.factory/[<prefix>/]factory.yaml>] \
  [--backup-dir <dir>] [--gcloud-config <name>] [--skip-customer-image-build] [--allow-hub-customer-image-build] \
  [--harness-image-antigravity <digest-or-registry-ref>] [--harness-image-claude <digest-or-registry-ref>] \
  [--start-coordinator | --no-start-coordinator] [--allow-unpushed-factory]
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
    --config) CONFIG_PATH="$2"; shift 2 ;;
    --gcloud-config) GCLOUD_CONFIG="$2"; shift 2 ;;
    --skip-customer-image-build) SKIP_CUSTOMER_IMAGE_BUILD="true"; shift ;;
    --allow-hub-customer-image-build) ALLOW_HUB_CUSTOMER_IMAGE_BUILD="true"; shift ;;
    --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
    --harness-image-antigravity) HARNESS_IMAGE_ANTIGRAVITY="$2"; shift 2 ;;
    --harness-image-claude) HARNESS_IMAGE_CLAUDE="$2"; shift 2 ;;
    --start-coordinator) START_COORDINATOR="true"; shift ;;
    --no-start-coordinator) START_COORDINATOR="false"; shift ;;
    --allow-unpushed-factory) ALLOW_UNPUSHED_FACTORY="true"; shift ;;
    *) echo "Unknown flag: $1" >&2; usage ;;
  esac
done

[[ -n "$KIT_DIR" && -n "$HUB_URL" ]] || usage
# Normalize CLI paths before switching cwd to TARGET_REPO so project-scoped `scion` commands
# resolve TARGET_REPO/.scion and .git even when invoked from another directory (HC14-F1).
KIT_DIR="$(cd "$KIT_DIR" && pwd)"
if [[ -n "$LANDING_ZONE_JSON" && -f "$LANDING_ZONE_JSON" ]]; then
  LANDING_ZONE_JSON="$(cd "$(dirname "$LANDING_ZONE_JSON")" && pwd)/$(basename "$LANDING_ZONE_JSON")"
fi
if [[ -n "$BACKUP_DIR" ]]; then
  mkdir -p "$BACKUP_DIR"
  BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"
fi
if [[ -n "$CONFIG_PATH" && -z "$TARGET_REPO" ]]; then
  echo "ERROR: --config requires --repo <target-repo-dir>." >&2
  exit 2
fi
if [[ -n "$TARGET_REPO" && -d "$TARGET_REPO" ]]; then
  TARGET_REPO="$(cd "$TARGET_REPO" && pwd -P)"
  if [[ -n "$CONFIG_PATH" ]]; then
    # Normalize --config strictly relative to physical TARGET_REPO and reject escapes (L1).
    CONFIG_PATH="$(python3 - "$TARGET_REPO" "$CONFIG_PATH" <<'PYEOF'
import os, pathlib, sys
repo = pathlib.Path(sys.argv[1]).resolve()
raw = pathlib.Path(sys.argv[2])
target = raw.resolve() if raw.is_absolute() else (repo / raw).resolve()
try:
    rel = target.relative_to(repo).as_posix()
except ValueError:
    print(f"ERROR: --config '{sys.argv[2]}' escapes --repo '{repo}'.", file=sys.stderr)
    raise SystemExit(1)
print(rel)
PYEOF
)"
  fi
  cd "$TARGET_REPO"
fi
export SCION_HUB_ENDPOINT="$HUB_URL"
if [[ -n "$PROJECT_SLUG" ]]; then
  PROJ_FLAGS=(--project "$PROJECT_SLUG")
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required CLI: $1" >&2; exit 1; }
}

parse_repo_cfg() {
  local pack_name="$1"
  local cfg_args=()
  if [[ -n "$CONFIG_PATH" ]]; then
    cfg_args=(--config "$CONFIG_PATH")
  fi
  if [[ -n "$TARGET_REPO" && ( -n "$CONFIG_PATH" || -f "$TARGET_REPO/.factory/factory.yaml" || -f "$TARGET_REPO/.factory/hub-project.yaml" ) ]]; then
    require_cmd python3
    python3 "$SCRIPT_DIR/parse_hub_project.py" --repo "$TARGET_REPO" --expected-pack "$pack_name" "${cfg_args[@]}"
  else
    cat <<'JSON'
{"schema_version":"1","slug":"","config_rel_path":".factory/hub-project.yaml","coordinator_brief_rel":".factory/coordinator-bootstrap-brief.md","pack":"","mode":"sandbox-direct","deploy_target":"","existing_hub":false,"diversity_profile":"cross-model","limits":{"default_max_duration":"2h","default_max_turns":60,"default_max_model_calls":150,"auto_suspend_idle":true},"exclude_skills":[],"overlay_skills":[],"kaizen":{"enabled":true,"schedule_cron":"0 0 * * *","time_zone":"America/Sao_Paulo","coordinator_agent":"coordinator","enable_gcp_obs":false},"harnesses":{"default":"antigravity-vertex","claude_model_garden_enabled":false,"vertex_gemini_location":"global","vertex_claude_region":"global"},"model_routing":{},"monorepo":{"enabled":false,"subdir":"","agent_prefix":""},"roster":{"preset":"lean","enabled_roles":[],"disabled_roles":[],"max_wip":3,"reviewer_replicas":1},"toolchain":{"dockerfile":"","tester_dockerfile":"","verify_binaries":[],"pinned_image":""},"intake":{"enabled":false,"provider":"github","max_concurrent_issues":2,"scope_label":"","release_label":"factory:ready","hold_label":"factory:hold","cadence_cron":"*/5 * * * *","time_zone":"America/Sao_Paulo","paused":false}}
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
  local pack_name pack_prefix repo_cfg disabled_roles_json mode deploy_target coord_tpl brief_rel has_brief="false"
  pack_name="$(jq -re '.pack' "$KIT_DIR/manifest.json")"
  pack_prefix="$(jq -re '.pack_prefix // .pack' "$KIT_DIR/manifest.json")"
  repo_cfg="$(parse_repo_cfg "$pack_name")"
  disabled_roles_json="$(jq -c '.roster.disabled_roles // []' <<< "$repo_cfg")"
  mode="$(jq -re '.mode' <<< "$repo_cfg")"
  deploy_target="$(jq -r '.deploy_target // ""' <<< "$repo_cfg")"
  coord_tpl="${pack_prefix}-coordinator"
  brief_rel="$(jq -r '.coordinator_brief_rel // ".factory/coordinator-bootstrap-brief.md"' <<< "$repo_cfg")"
  if [[ -n "$TARGET_REPO" && -f "$TARGET_REPO/$brief_rel" ]]; then
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
  # Store default backups outside TARGET_REPO so apply never leaves untracked .backups/ in customer repos (HC14-F1).
  dir="${BACKUP_DIR:-${TMPDIR:-/tmp}/scion-hub-backups/$ts}"
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
  # Checks whether the Hub project already uses an active Scion GitHub App (zero-PAT short-lived tokens)
  # before warning about missing GITHUB_TOKEN with injectionMode=always (HC-10 F4, Scion v0.4.0-preview.4, H3).
  local proj_id="$1"
  [[ -n "$proj_id" && -n "${SCION_HUB_TOKEN:-}" ]] || return 0
  validate_uuid_or_fail "$proj_id" "warn_github_token_injection_mode" || return 0
  local proj_json gh_install_id="" gh_app_state=""
  proj_json="$(curl -sf -H "Authorization: Bearer ${SCION_HUB_TOKEN}" "${HUB_URL%/}/api/v1/projects/${proj_id}" 2>/dev/null || true)"
  if [[ -n "$proj_json" ]]; then
    gh_install_id="$(jq -r '(.githubInstallationId // .github_installation_id // .project.githubInstallationId // .project.github_installation_id // "") | tostring' <<< "$proj_json" 2>/dev/null || echo "")"
    gh_app_state="$(jq -r '
      (.githubAppStatus // .github_app_status // .project.githubAppStatus // .project.github_app_status // "")
      | if type == "object" then (.state // "") else tostring end
    ' <<< "$proj_json" 2>/dev/null || echo "")"
    if [[ "$gh_install_id" =~ ^[1-9][0-9]*$ && "$gh_app_state" == "ok" ]]; then
      echo "GITHUB APP ACTIVE: project ${proj_id} uses short-lived Scion GitHub App tokens (installation=${gh_install_id}; PAT not required)."
      return 0
    fi
  fi
  local sec_json mode
  sec_json="$(curl -sf -H "Authorization: Bearer ${SCION_HUB_TOKEN}" "${HUB_URL%/}/api/v1/secrets?scope=project&scopeId=${proj_id}" 2>/dev/null || true)"
  [[ -n "$sec_json" ]] || return 0
  mode="$(jq -r '((.secrets // .)[]? | select(.key == "GITHUB_TOKEN") | (.injectionMode // .injection_mode)) // empty' <<< "$sec_json" | head -n 1 || true)"
  if [[ "$mode" != "always" ]]; then
    echo "WARNING: Project has no active GitHub App (state='${gh_app_state:-unset}') and GITHUB_TOKEN has injectionMode='${mode:-missing}' (expected 'always' for private clones)." >&2
    echo "  Recommended (zero-PAT): configure Scion GitHub App in Hub Admin UI (/admin/server-config -> GitHub App)." >&2
    echo "  Fallback (PAT): scion hub secret set --project GITHUB_TOKEN \"\$(gh auth token)\" --hub \"$HUB_URL\"" >&2
    echo "  Fallback (PAT): scion hub secret update --project GITHUB_TOKEN --injection-mode always --hub \"$HUB_URL\"" >&2
  fi
}

resolve_repo_base_branch() {
  # Resolves the git base branch from factory config or origin tracking refs (shared by landed-check and git archive).
  local target_cfg_rel="${1:-}"
  local remote_head base_branch=""
  for cfg_cand in "$TARGET_REPO/$target_cfg_rel" "$TARGET_REPO/.factory/factory-profile.yaml"; do
    if [[ -n "$target_cfg_rel" || "$cfg_cand" == *factory-profile.yaml ]]; then
      if [[ -z "$base_branch" && -f "$cfg_cand" ]]; then
        base_branch="$(python3 -c 'import sys, yaml; d=yaml.safe_load(open(sys.argv[1])) or {}; print(((d.get("git_flow") or {}).get("base_branch")) or "")' "$cfg_cand" 2>/dev/null || true)"
      fi
    fi
  done
  if [[ -z "$base_branch" ]]; then
    remote_head="$(git -C "$TARGET_REPO" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
    base_branch="${remote_head#origin/}"
  fi
  if [[ -z "$base_branch" ]]; then
    for cand in main master; do
      if git -C "$TARGET_REPO" rev-parse --verify "refs/remotes/origin/${cand}" >/dev/null 2>&1; then
        base_branch="$cand"
        break
      fi
    done
  fi
  printf '%s' "$base_branch"
}

check_remote_factory_landed() {
  # Verifies the resolved factory config and any v2 toolchain Dockerfiles are pushed to origin/<base_branch>
  # BEFORE mutating Hub state or submitting Cloud Build archives (UX-C1, M1, Wave 2 M9).
  local repo_cfg="${1:-}"
  [[ -n "$TARGET_REPO" && -d "$TARGET_REPO" ]] || return 0
  [[ "$ALLOW_UNPUSHED_FACTORY" != "true" ]] || return 0
  command -v git >/dev/null 2>&1 || return 0
  git -C "$TARGET_REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
  git -C "$TARGET_REPO" remote get-url origin >/dev/null 2>&1 || return 0

  local target_cfg_rel="" schema_ver="1" df_rel="" tester_df_rel=""
  if [[ -n "$repo_cfg" ]]; then
    target_cfg_rel="$(jq -r '.config_rel_path // ""' <<< "$repo_cfg")"
    schema_ver="$(jq -r '.schema_version // "1"' <<< "$repo_cfg")"
    df_rel="$(jq -r '.toolchain.dockerfile // ""' <<< "$repo_cfg")"
    tester_df_rel="$(jq -r '.toolchain.tester_dockerfile // ""' <<< "$repo_cfg")"
  fi
  if [[ -z "$target_cfg_rel" ]]; then
    if [[ -n "$CONFIG_PATH" ]]; then
      target_cfg_rel="$CONFIG_PATH"
    elif [[ -f "$TARGET_REPO/.factory/factory.yaml" ]]; then
      target_cfg_rel=".factory/factory.yaml"
    else
      target_cfg_rel=".factory/hub-project.yaml"
    fi
  fi

  local base_branch
  base_branch="$(resolve_repo_base_branch "$target_cfg_rel")"
  [[ -n "$base_branch" ]] || return 0

  # Refresh remote tracking ref best-effort so recently merged PRs do not trigger stale local failures (M1).
  git -C "$TARGET_REPO" fetch origin "$base_branch" --quiet 2>/dev/null || true

  if git -C "$TARGET_REPO" rev-parse --verify "refs/remotes/origin/${base_branch}" >/dev/null 2>&1; then
    local required_paths=("$target_cfg_rel")
    if [[ "$schema_ver" == "2" ]]; then
      [[ -n "$df_rel" ]] && required_paths+=("$df_rel")
      [[ -n "$tester_df_rel" ]] && required_paths+=("$tester_df_rel")
    fi
    local req_rel
    for req_rel in "${required_paths[@]}"; do
      if ! git -C "$TARGET_REPO" ls-tree -r --name-only "refs/remotes/origin/${base_branch}" -- "$req_rel" 2>/dev/null | grep -q .; then
        echo "APPLY FAILED: ${req_rel} is not landed on origin/${base_branch}." >&2
        echo "  Remote Scion containers and Cloud Build archives use origin/${base_branch} and will not see local-only .factory/ files." >&2
        echo "  If you just merged the PR on GitHub, run: git -C \"$TARGET_REPO\" fetch origin ${base_branch}" >&2
        echo "  Otherwise run: factory_onboard.py emit --pr (or pass --allow-unpushed-factory for local tests)." >&2
        exit 1
      fi
      if [[ -f "$TARGET_REPO/$req_rel" ]] && ! git -C "$TARGET_REPO" diff --quiet "refs/remotes/origin/${base_branch}" -- "$req_rel" 2>/dev/null; then
        echo "WARNING: Local ${req_rel} differs from origin/${base_branch}. Push/merge changes so remote builds and containers match." >&2
      fi
    done
  fi
}

_build_one_customer_dockerfile() {
  # Lints, archives, builds via isolated Cloud Build, verifies binaries inside `docker build --network=none`
  # as non-root `scion` (never executing the customer image as a Cloud Build step, C1), and prints the pinned digest ref.
  local df_rel="$1" verify_json="$2" base_img="$3" build_project="$4" region="$5" build_ar="$6" build_sa="$7" sa_project="$8" staging_bkt="$9" image_name="${10}" base_branch="${11}"
  local df_abs="$TARGET_REPO/$df_rel"
  [[ -f "$df_abs" ]] || { echo "APPLY FAILED: Declared Dockerfile '${df_rel}' does not exist." >&2; exit 1; }

  echo "=== CUSTOMER DOCKERFILE LINT (4-rule fail-closed): ${df_rel} ===" >&2
  python3 "$SCRIPT_DIR/parse_hub_project.py" \
    --lint-dockerfile "$df_abs" \
    --verify-binaries-json "$verify_json" >&2

  if [[ "$SKIP_CUSTOMER_IMAGE_BUILD" == "true" ]]; then
    echo "SKIP customer image build for ${df_rel} (--skip-customer-image-build set)." >&2
    return 0
  fi

  local tmp_ctx tmp_cb target_tag="${build_ar}/${image_name}:latest"
  tmp_ctx="$(mktemp -d)"
  tmp_cb="$(mktemp -d)"
  TMP_CLEANUP_DIRS+=("$tmp_ctx" "$tmp_cb")

  # Archive strictly from refs/remotes/origin/<base_branch> unless --allow-unpushed-factory is set (M9).
  if [[ "$ALLOW_UNPUSHED_FACTORY" != "true" ]] \
    && command -v git >/dev/null 2>&1 \
    && git -C "$TARGET_REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    && [[ -n "$base_branch" ]] \
    && git -C "$TARGET_REPO" rev-parse --verify "refs/remotes/origin/${base_branch}" >/dev/null 2>&1; then
    echo "=== ARCHIVING COMMITTED CONTEXT FROM origin/${base_branch} (M9) ===" >&2
    git -C "$TARGET_REPO" archive "refs/remotes/origin/${base_branch}" | tar -x -C "$tmp_ctx"
  else
    tar -C "$TARGET_REPO" --exclude='.git' --exclude='.scion' -cf - . | tar -x -C "$tmp_ctx"
  fi
  [[ -f "$tmp_ctx/$df_rel" ]] || { echo "APPLY FAILED: ${df_rel} missing in archived build context." >&2; exit 1; }

  # Build a network-isolated verification Dockerfile using JSON exec-form RUN as USER scion (C1).
  python3 - "$tmp_cb/cloudbuild.yaml" "$tmp_ctx/.scion-verify.Dockerfile" "$df_rel" "$base_img" "$target_tag" "$verify_json" <<'PYEOF'
import json, pathlib, re, shlex, sys, yaml

cb_path, verify_df_path, df_rel, base_img, target_tag, verify_raw = sys.argv[1:7]
VERIFY_RE = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,31}( (--version|-version|version|--help|playwright --version))?$")
verify_cmds = json.loads(verify_raw) if verify_raw else []
lines = [f"FROM {target_tag}", "USER scion"]
for cmd in verify_cmds:
    s = str(cmd).strip()
    if not VERIFY_RE.fullmatch(s):
        raise SystemExit(f"ERROR: Unsafe toolchain.verify_binaries command rejected: {s!r}")
    argv = shlex.split(s)
    lines.append(f"RUN {json.dumps(argv)}")
if not verify_cmds:
    lines.append('RUN ["id"]')
pathlib.Path(verify_df_path).write_text("\n".join(lines) + "\n", encoding="utf-8")

cb = {
    "steps": [
        {
            "name": "gcr.io/cloud-builders/docker",
            "id": "build-customer-runtime",
            "args": ["build", "-f", df_rel, "--build-arg", f"BASE_IMAGE={base_img}", "-t", target_tag, "."],
        },
        {
            "name": "gcr.io/cloud-builders/docker",
            "id": "verify-binaries-network-none",
            "args": ["build", "--network=none", "-f", ".scion-verify.Dockerfile", "."],
        },
    ],
    "images": [target_tag],
    "options": {"logging": "CLOUD_LOGGING_ONLY"},
}
pathlib.Path(cb_path).write_text(yaml.safe_dump(cb, sort_keys=False), encoding="utf-8")
PYEOF

  local gcloud_flags=()
  if [[ -n "$GCLOUD_CONFIG" ]]; then
    gcloud_flags+=(--configuration="$GCLOUD_CONFIG")
  fi
  echo "=== CUSTOMER DOCKERFILE BUILD + ISOLATED VERIFY_BINARIES: ${df_rel} -> ${target_tag} (project=${build_project}, sa=${build_sa}) ===" >&2
  gcloud "${gcloud_flags[@]}" builds submit "$tmp_ctx" \
    --project="$build_project" \
    --region="$region" \
    --config="$tmp_cb/cloudbuild.yaml" \
    --service-account="projects/${sa_project}/serviceAccounts/${build_sa}" \
    --gcs-source-staging-dir="gs://${staging_bkt}/customer-images/${image_name}" \
    --quiet >&2

  local digest
  digest="$(gcloud "${gcloud_flags[@]}" artifacts docker images describe "$target_tag" \
    --project="$build_project" --format='value(image_summary.digest)')"
  [[ "$digest" == sha256:* ]] || { echo "APPLY FAILED: Could not resolve @sha256 digest for ${target_tag}." >&2; exit 1; }
  printf '%s' "${build_ar}/${image_name}@${digest}"
}

build_and_pin_customer_dockerfile() {
  # Runs only for schema_version 2 (M4). Builds core Dockerfile.customer (and optional Dockerfile.tester, H2)
  # using the isolated Sandbox Cloud Build SA when available, or fails closed on 2-project Hubs unless
  # --allow-hub-customer-image-build is explicitly passed (C1, costela H3).
  local repo_cfg="$1" pack_name="$2" pack_prefix="$3"
  local schema_ver df_rel tester_df_rel verify_json
  schema_ver="$(jq -r '.schema_version // "1"' <<< "$repo_cfg")"
  [[ "$schema_ver" == "2" ]] || return 0
  df_rel="$(jq -r '.toolchain.dockerfile // ""' <<< "$repo_cfg")"
  tester_df_rel="$(jq -r '.toolchain.tester_dockerfile // ""' <<< "$repo_cfg")"
  [[ ( -n "$df_rel" || -n "$tester_df_rel" ) && -n "$TARGET_REPO" ]] || return 0

  verify_json="$(jq -c '.toolchain.verify_binaries // []' <<< "$repo_cfg")"
  if [[ "$SKIP_CUSTOMER_IMAGE_BUILD" == "true" ]]; then
    [[ -n "$df_rel" ]] && python3 "$SCRIPT_DIR/parse_hub_project.py" --lint-dockerfile "$TARGET_REPO/$df_rel" --verify-binaries-json "$verify_json"
    [[ -n "$tester_df_rel" ]] && python3 "$SCRIPT_DIR/parse_hub_project.py" --lint-dockerfile "$TARGET_REPO/$tester_df_rel" --verify-binaries-json "[]"
    echo "SKIP customer image build (--skip-customer-image-build set)."
    return 0
  fi
  if [[ -z "$LANDING_ZONE_JSON" || ! -f "$LANDING_ZONE_JSON" ]]; then
    [[ -n "$df_rel" ]] && python3 "$SCRIPT_DIR/parse_hub_project.py" --lint-dockerfile "$TARGET_REPO/$df_rel" --verify-binaries-json "$verify_json"
    [[ -n "$tester_df_rel" ]] && python3 "$SCRIPT_DIR/parse_hub_project.py" --lint-dockerfile "$TARGET_REPO/$tester_df_rel" --verify-binaries-json "[]"
    echo "WARNING: Skipping customer Dockerfile Cloud Build (no --landing-zone outputs JSON provided)." >&2
    return 0
  fi

  local hub_p region hub_ar hub_sa sbx_p sbx_ar sbx_sa staging_bkt base_img
  local build_project build_ar build_sa sa_project
  hub_p="$(jq -r '.hub_project_id.value // empty' "$LANDING_ZONE_JSON")"
  region="$(jq -r '.region.value // "us-central1"' "$LANDING_ZONE_JSON")"
  hub_ar="$(jq -r '.artifact_registry_url.value // empty' "$LANDING_ZONE_JSON")"
  hub_sa="$(jq -r '.release_builder_sa_email.value // empty' "$LANDING_ZONE_JSON")"
  sbx_p="$(jq -r '.sandbox_project_id.value // empty' "$LANDING_ZONE_JSON")"
  sbx_ar="$(jq -r '.sandbox_artifact_registry_url.value // empty' "$LANDING_ZONE_JSON")"
  sbx_sa="$(jq -r '.sandbox_builder_sa_email.value // empty' "$LANDING_ZONE_JSON")"
  staging_bkt="$(jq -r '.sandbox_staging_bucket.value // empty' "$LANDING_ZONE_JSON")"
  base_img="${HARNESS_IMAGE_ANTIGRAVITY:-$(jq -r --arg k "${pack_name}-antigravity-runtime" '.images[$k] // empty' "$KIT_DIR/manifest.json")}"

  if [[ ! "$base_img" =~ @sha256:[0-9a-f]{64}$ ]]; then
    echo "APPLY FAILED: Base antigravity image '${base_img:-missing}' is not pinned to an immutable @sha256 digest (H1-j)." >&2
    exit 1
  fi
  [[ -n "$staging_bkt" ]] || { echo "APPLY FAILED: Missing sandbox_staging_bucket in landing-zone outputs." >&2; exit 1; }

  if [[ -n "$sbx_p" && -n "$sbx_ar" && -n "$sbx_sa" ]]; then
    build_project="$sbx_p"
    build_ar="$sbx_ar"
    build_sa="$sbx_sa"
    sa_project="$sbx_p"
  elif [[ "$ALLOW_HUB_CUSTOMER_IMAGE_BUILD" == "true" ]]; then
    [[ -n "$hub_p" && -n "$hub_ar" && -n "$hub_sa" ]] || { echo "APPLY FAILED: Missing Hub builder outputs in landing-zone JSON." >&2; exit 1; }
    build_project="$hub_p"
    build_ar="$hub_ar"
    build_sa="$hub_sa"
    sa_project="$hub_p"
    echo "WARNING: Building customer Dockerfile inside Hub project '${hub_p}' (--allow-hub-customer-image-build set; no Sandbox project provisioned)." >&2
  else
    echo "APPLY FAILED: Refusing to build customer Dockerfile with Hub release_builder SA (costela H3 / C1)." >&2
    echo "  Provision the isolated Sandbox project (enable_sandbox_project=true), OR pass --allow-hub-customer-image-build on 2-project Hubs." >&2
    exit 1
  fi

  local cfg_slug mono_prefix origin_url="" origin_hash="" img_slug base_branch target_cfg_rel
  cfg_slug="$(jq -r '(.slug // "") | if . == "" then "customer" else . end' <<< "$repo_cfg")"
  mono_prefix="$(jq -r 'if .monorepo.enabled then (.monorepo.agent_prefix // "") else "" end' <<< "$repo_cfg")"
  target_cfg_rel="$(jq -r '.config_rel_path // ""' <<< "$repo_cfg")"
  base_branch="$(resolve_repo_base_branch "$target_cfg_rel")"
  if command -v git >/dev/null 2>&1 && git -C "$TARGET_REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    origin_url="$(git -C "$TARGET_REPO" remote get-url origin 2>/dev/null || true)"
  fi
  if [[ -n "$origin_url" ]]; then
    origin_hash="$(printf '%s' "$origin_url" | python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.read().strip().encode()).hexdigest()[:6])')"
  fi
  img_slug="${cfg_slug}${mono_prefix:+-$mono_prefix}${origin_hash:+-$origin_hash}"

  if [[ -n "$df_rel" ]]; then
    HARNESS_IMAGE_ANTIGRAVITY="$(_build_one_customer_dockerfile "$df_rel" "$verify_json" "$base_img" "$build_project" "$region" "$build_ar" "$build_sa" "$sa_project" "$staging_bkt" "${img_slug}-antigravity" "$base_branch")"
    echo "PINNED CUSTOMER RUNTIME IMAGE: ${HARNESS_IMAGE_ANTIGRAVITY}"
  fi
  if [[ -n "$tester_df_rel" ]]; then
    HARNESS_IMAGE_TESTER="$(_build_one_customer_dockerfile "$tester_df_rel" "[]" "$base_img" "$build_project" "$region" "$build_ar" "$build_sa" "$sa_project" "$staging_bkt" "${img_slug}-tester-antigravity" "$base_branch")"
    echo "PINNED CUSTOMER TESTER IMAGE: ${HARNESS_IMAGE_TESTER}"
  fi
}

print_delta_watcher_alignment() {
  # Prints copy-ready Stage 02 Delta Watcher variables synchronized with .factory/hub-project.yaml intake and coordinator_agent (UX-C2).
  local repo_cfg="$1" pack_prefix="$2" proj_id="${3:-}"
  local dw_enabled dw_provider dw_cap dw_rel dw_hold dw_scope dw_cron dw_tz dw_paused coord_name
  dw_enabled="$(jq -r '(.intake.enabled // false) | tostring' <<< "$repo_cfg")"
  [[ "$dw_enabled" == "true" ]] || return 0
  dw_provider="$(jq -r '.intake.provider // "github"' <<< "$repo_cfg")"
  dw_cap="$(jq -r '.intake.max_concurrent_issues // 2' <<< "$repo_cfg")"
  dw_rel="$(jq -r '.intake.release_label // "factory:ready"' <<< "$repo_cfg")"
  dw_hold="$(jq -r '.intake.hold_label // "factory:hold"' <<< "$repo_cfg")"
  dw_scope="$(jq -r '.intake.scope_label // ""' <<< "$repo_cfg")"
  dw_cron="$(jq -r '.intake.cadence_cron // "*/5 * * * *"' <<< "$repo_cfg")"
  dw_tz="$(jq -r '.intake.time_zone // "America/Sao_Paulo"' <<< "$repo_cfg")"
  dw_paused="$(jq -r '(.intake.paused // false) | tostring' <<< "$repo_cfg")"
  coord_name="$(jq -r --arg p "$pack_prefix" '.kaizen.coordinator_agent // ($p + "-coordinator")' <<< "$repo_cfg")"
  echo "=== NEXT STEP: Stage 02 External Delta Watcher Alignment (provider=${dw_provider}) ==="
  if [[ "$dw_provider" != "github" ]]; then
    echo "  NOTE: External Delta Watcher natively polls GitHub. For '${dw_provider}', keep enable_delta_watcher = false and trigger runs manually via Hub UI/CLI."
    return 0
  fi
  echo "  enable_delta_watcher                = true"
  echo "  delta_watcher_coordinator_agent     = \"${coord_name}\""
  if [[ -n "$proj_id" ]]; then echo "  delta_watcher_scion_project_id      = \"${proj_id}\""; fi
  echo "  delta_watcher_max_concurrent_issues = ${dw_cap}"
  echo "  delta_watcher_release_label         = \"${dw_rel}\""
  echo "  delta_watcher_hold_label            = \"${dw_hold}\""
  if [[ -n "$dw_scope" ]]; then echo "  delta_watcher_scope_label           = \"${dw_scope}\""; fi
  echo "  delta_watcher_cadence_cron          = \"${dw_cron}\""
  echo "  delta_watcher_time_zone             = \"${dw_tz}\""
  echo "  delta_watcher_paused                = ${dw_paused}"
}

ensure_delta_watcher_hub_rbac() {
  # Pre-registers the External Delta Watcher SA as a Hub user and grants a 2-permission project role
  # (agent.message and agent.read only) so Cloud Run OIDC wakes succeed without Hub admin rights (HC13-F7).
  local proj_id="$1"
  [[ -n "$proj_id" && -n "${SCION_HUB_TOKEN:-}" && -n "$LANDING_ZONE_JSON" && -f "$LANDING_ZONE_JSON" ]] || return 0
  validate_uuid_or_fail "$proj_id" "ensure_delta_watcher_hub_rbac" || return 0
  local dw_sa
  dw_sa="$(jq -r '.delta_watcher_sa_email.value // empty' "$LANDING_ZONE_JSON")"
  [[ -n "$dw_sa" ]] || return 0

  # Provision user idempotently or look up an already-federated user record by email.
  local dw_uid="" users_json=""
  users_json="$(curl -sf -H "Authorization: Bearer ${SCION_HUB_TOKEN}" "${HUB_URL%/}/api/v1/users" 2>/dev/null || true)"
  if [[ -n "$users_json" ]]; then
    dw_uid="$(jq -r --arg e "$dw_sa" '(.users // .items // [])[] | select(.email == $e) | .id' <<< "$users_json" | head -n 1 || true)"
  fi
  if [[ -z "$dw_uid" ]]; then
    dw_uid="$(scion hub users provision "$dw_sa" --display-name "External Delta Watcher" --json --hub "$HUB_URL" 2>/dev/null | jq -r '.id // .user.id // empty' || true)"
  fi
  if [[ -z "$dw_uid" ]]; then
    echo "WARNING: Could not provision Delta Watcher user '${dw_sa}' on Hub; skipping role binding." >&2
    return 0
  fi

  # Ensure the custom 2-permission project role exists (agent.message + agent.read only).
  local roles_json="" role_id=""
  roles_json="$(curl -sf -H "Authorization: Bearer ${SCION_HUB_TOKEN}" "${HUB_URL%/}/api/v1/admin/roles" 2>/dev/null || true)"
  if [[ -n "$roles_json" ]]; then
    role_id="$(jq -r '(.roles // .items // [])[] | select(.name == "delta-watcher-messenger") | .id' <<< "$roles_json" | head -n 1 || true)"
  fi
  if [[ -z "$role_id" ]]; then
    role_id="$(curl -sf -X POST \
      -H "Authorization: Bearer ${SCION_HUB_TOKEN}" \
      -H "Content-Type: application/json" \
      "${HUB_URL%/}/api/v1/admin/roles" \
      -d '{"name":"delta-watcher-messenger","description":"Least-privilege External Delta Watcher wake-only role","scopeType":"project","permissions":["agent.message","agent.read"]}' 2>/dev/null \
      | jq -r '.id // .role.id // empty' || true)"
  fi
  if [[ -z "$role_id" ]]; then
    echo "WARNING: Hub /api/v1/admin/roles unavailable; bind delta-watcher-messenger manually for '${dw_sa}'." >&2
    return 0
  fi

  # Bind delta-watcher-messenger strictly to this project UUID if not already present.
  local bindings_json="" existing_binding=""
  bindings_json="$(curl -sf -H "Authorization: Bearer ${SCION_HUB_TOKEN}" \
    "${HUB_URL%/}/api/v1/admin/role-bindings?principalType=user&principalId=${dw_uid}" 2>/dev/null || true)"
  if [[ -n "$bindings_json" ]]; then
    existing_binding="$(jq -r --arg rid "$role_id" --arg pid "$proj_id" \
      '(.bindings // .items // [])[] | select(.roleDefinitionId == $rid and .scopeType == "project" and .scopeId == $pid) | .id' \
      <<< "$bindings_json" | head -n 1 || true)"
  fi
  if [[ -n "$existing_binding" ]]; then
    echo "EXISTING DELTA WATCHER RBAC: ${dw_sa} -> delta-watcher-messenger on project ${proj_id} (${existing_binding})"
    return 0
  fi
  curl -sf -X POST \
    -H "Authorization: Bearer ${SCION_HUB_TOKEN}" \
    -H "Content-Type: application/json" \
    "${HUB_URL%/}/api/v1/admin/role-bindings" \
    -d "{\"principalType\":\"user\",\"principalId\":\"${dw_uid}\",\"roleDefinitionId\":\"${role_id}\",\"scopeType\":\"project\",\"scopeId\":\"${proj_id}\"}" >/dev/null
  echo "BOUND DELTA WATCHER RBAC: ${dw_sa} -> delta-watcher-messenger (agent.message, agent.read) on project ${proj_id}"
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
    generic) var_prefix="GENERIC" ;;
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
  local pack_prefix="$1" kz_enabled="$2" kz_cron="$3" kz_tz="$4" kz_coord="$5" kz_gcp_obs="${6:-false}" existing_hub="${7:-false}" mono_enabled="${8:-false}"
  if [[ "$kz_enabled" != "true" ]]; then
    echo "KAIZEN SCHEDULE: explicitly disabled via factory config (kaizen.enabled=false)."
    return 0
  fi
  local sched_name="daily-kaizen"
  # Scope schedule name per coordinator in monorepo or shared-Hub factories so sibling schedules never clobber each other (H3).
  if [[ ( "$mono_enabled" == "true" || "$existing_hub" == "true" ) && -n "$kz_coord" && "$kz_coord" != "coordinator" && "$kz_coord" != "${pack_prefix}-coordinator" ]]; then
    sched_name="daily-kaizen-${kz_coord}"
  fi
  local sched_json existing_match stale_ids kz_sa_hint="worker SA"
  if [[ "$kz_gcp_obs" == "true" ]]; then
    kz_sa_hint="kaizen-viewer SA"
  fi
  sched_json="$(scion --format json schedule list --show recurring "${PROJ_FLAGS[@]}" --hub "$HUB_URL")"
  # Reconcile idempotently matching both schedule name and target coordinator agent (H3).
  existing_match="$(jq -r --arg sn "$sched_name" --arg coord "$kz_coord" --arg c "$kz_cron" --arg tz "$kz_tz" '((if type == "array" then . elif (.schedules | type) == "object" then (.schedules.schedules // []) elif (.schedules | type) == "array" then .schedules else (.items // []) end)[] | select(.name == $sn and ((.agent // .targetAgent // $coord) == $coord) and ((.cronExpr // $c) == $c) and ((.timeZone // $tz) == $tz)) | .id) // empty' <<< "$sched_json" | head -n 1)"
  if [[ -n "$existing_match" ]]; then
    echo "SKIP schedule: ${sched_name} ($existing_match) already registered (${kz_cron} ${kz_tz} -> ${kz_coord})."
    return 0
  fi
  stale_ids="$(jq -r --arg sn "$sched_name" --arg coord "$kz_coord" '((if type == "array" then . elif (.schedules | type) == "object" then (.schedules.schedules // []) elif (.schedules | type) == "array" then .schedules else (.items // []) end)[] | select((.name == $sn or ($sn == "daily-kaizen" and .name == "weekly-kaizen")) and ((.agent // .targetAgent // $coord) == $coord)) | .id) // empty' <<< "$sched_json" || true)"
  while IFS= read -r stale_id; do
    [[ -n "$stale_id" ]] || continue
    scion schedule delete "$stale_id" "${PROJ_FLAGS[@]}" --hub "$HUB_URL" >/dev/null 2>&1 || true
  done <<< "$stale_ids"
  scion schedule create-recurring \
    --name "$sched_name" \
    --cron "$kz_cron" \
    --time-zone "$kz_tz" \
    --type message \
    --agent "$kz_coord" \
    --wake \
    --message "Run daily closed-loop Kaizen cycle: spawn ${pack_prefix}-kaizen-analyst (--role baseline, ${kz_sa_hint}), collect 0-token telemetry, publish report and Artifact, then retire it." \
    "${PROJ_FLAGS[@]}" \
    --hub "$HUB_URL"
  echo "SCHEDULED KAIZEN: ${sched_name} (${kz_cron} ${kz_tz} -> ${kz_coord} --wake)"
}

ensure_coordinator_started() {
  local pack_prefix="$1" default_harness="$2" repo_cfg="$3" worker_sa="$4" hc_prefix="${5:-$1}"
  local coord_name coord_tpl coord_harness coord_model coord_thinking disabled_json coord_disabled brief_rel cfg_rel
  coord_name="$(jq -re --arg p "$pack_prefix" '.kaizen.coordinator_agent // ($p + "-coordinator")' <<< "$repo_cfg")"
  coord_tpl="${pack_prefix}-coordinator"
  coord_harness="$(jq -r --arg d "$default_harness" '.model_routing.coordinator.harness // $d' <<< "$repo_cfg")"
  coord_harness="${hc_prefix}-${coord_harness}"
  coord_model="$(jq -r '.model_routing.coordinator.model // empty' <<< "$repo_cfg")"
  coord_thinking="$(jq -r '.model_routing.coordinator.thinking_level // empty' <<< "$repo_cfg")"
  disabled_json="$(jq -c '.roster.disabled_roles // []' <<< "$repo_cfg")"
  coord_disabled="$(jq -r --arg full "$coord_tpl" 'index("coordinator") != null or index($full) != null' <<< "$disabled_json")"
  brief_rel="$(jq -r '.coordinator_brief_rel // ".factory/coordinator-bootstrap-brief.md"' <<< "$repo_cfg")"
  cfg_rel="$(jq -r '.config_rel_path // ".factory/factory.yaml"' <<< "$repo_cfg")"

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
  if [[ -n "$TARGET_REPO" && -f "$TARGET_REPO/$brief_rel" ]]; then
    has_brief="true"
    start_args+=(--task-file "$TARGET_REPO/$brief_rel")
  else
    start_args+=("Read ${cfg_rel} and AGENTS.md. Post a concise standby readiness summary in Scion Chat and run sciontool status blocked until the Product Owner approves execution.")
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
    local existing_status
    existing_status="$(jq -r \
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
        | (.phase // .status // .state // "")) // empty' <<< "$list_json" | head -n 1 | tr '[:upper:]' '[:lower:]' || true)"
    if [[ "$existing_status" == "stopped" || "$existing_status" == "suspended" ]]; then
      echo "EXISTING COORDINATOR (${existing_status}): ${coord_name} -> revive via 'scion resume ${coord_name} --hub \"${HUB_URL}\"' (v0.4.0-preview.4 returns 409 on start)."
    else
      echo "SKIP coordinator start: ${coord_name} already exists on Hub."
    fi
    return 0
  fi

  # Protect the long-lived Coordinator from bulk `scion suspend --all` when running Scion v0.4.0-preview.4+.
  if scion help start 2>&1 | grep -q -- '--never-suspend'; then
    start_args+=(--never-suspend)
  fi

  scion "${start_args[@]}"
  echo "COORDINATOR STARTED (standby mode): ${coord_name} (template=${coord_tpl}, harness=${coord_harness})"
}

apply_hub_global_governance() {
  # Applies Hub-wide IAM policy, limits, lifecycle experiments, broker governance, and GCP telemetry (Phase A 1x).
  local max_dur="$1" max_turns="$2" max_calls="$3" auto_susp="$4"
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
  if [[ "$auto_susp" == "true" ]]; then
    scion hub experiments enable lifecycle.idle_suspend --hub "$HUB_URL"
  fi
  scion hub experiments enable lifecycle.never_suspend --hub "$HUB_URL" || true
  for _exp in web.decisions hub.artifacts web.artifact_review_editor hub.artifact_archive; do
    scion hub experiments enable "$_exp" --hub "$HUB_URL"
  done
  scion hub experiments enable hub.admin_managed_brokers --hub "$HUB_URL" \
    || echo "WARNING: Could not enable hub.admin_managed_brokers on ${HUB_URL}." >&2
  if [[ "${ENFORCE_ADMIN_MANAGED_BROKERS:-false}" == "true" ]]; then
    scion hub settings set broker_policy.admin_managed_only true --hub "$HUB_URL"
  fi
  if [[ -n "$LANDING_ZONE_JSON" && -f "$LANDING_ZONE_JSON" ]]; then
    local hub_p
    hub_p="$(jq -r '.hub_project_id.value // empty' "$LANDING_ZONE_JSON")"
    if [[ -n "$hub_p" ]]; then
      scion hub settings set telemetry.enabled true --hub "$HUB_URL"
      scion hub settings set telemetry.cloud.enabled true --hub "$HUB_URL"
      scion hub settings set telemetry.cloud.provider gcp --hub "$HUB_URL"
      scion hub settings set telemetry.cloud.gcp_project_id "$hub_p" --hub "$HUB_URL"
    fi
  fi
}

do_platform_init() {
  # Phase A one-time Hub initialization for 1-Hub->N-Factories deployments (H4, M2).
  do_preflight
  apply_hub_global_governance \
    "${PLATFORM_DEFAULT_MAX_DURATION:-2h}" \
    "${PLATFORM_DEFAULT_MAX_TURNS:-60}" \
    "${PLATFORM_DEFAULT_MAX_MODEL_CALLS:-150}" \
    "${PLATFORM_AUTO_SUSPEND_IDLE:-true}"
  echo "PLATFORM INIT COMPLETE."
}

do_apply() {
  do_preflight
  local pack_name pack_prefix repo_cfg mode max_dur max_turns max_calls auto_susp exclude_json
  pack_name="$(jq -re '.pack' "$KIT_DIR/manifest.json")"
  pack_prefix="$(jq -re '.pack_prefix // .pack' "$KIT_DIR/manifest.json")"
  repo_cfg="$(parse_repo_cfg "$pack_name")"
  if [[ -n "$TARGET_REPO" ]]; then
    check_remote_factory_landed "$repo_cfg"
  fi

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

  # 2. Lint, build, verify_binaries, and digest-pin custom .factory/[<prefix>/]Dockerfile.customer when declared,
  # then materialize Vertex AI project/region + real harness image and sync to Scion Hub.
  build_and_pin_customer_dockerfile "$repo_cfg" "$pack_name" "$pack_prefix"

  local default_harness claude_mg_enabled gemini_loc claude_reg existing_hub inf_proj="" hc_prefix="$pack_prefix" mono_enabled="false" mono_prefix="" cfg_slug="" df_declared="" tester_df_declared="" origin_url="" origin_hash=""
  default_harness="$(jq -re '.harnesses.default // "antigravity-vertex"' <<< "$repo_cfg")"
  claude_mg_enabled="$(jq -re '(.harnesses.claude_model_garden_enabled // false) | tostring' <<< "$repo_cfg")"
  gemini_loc="$(jq -re '.harnesses.vertex_gemini_location // "global"' <<< "$repo_cfg")"
  claude_reg="$(jq -re '.harnesses.vertex_claude_region // "global"' <<< "$repo_cfg")"
  existing_hub="$(jq -r '(.existing_hub // false) | tostring' <<< "$repo_cfg")"
  mono_enabled="$(jq -r '(.monorepo.enabled // false) | tostring' <<< "$repo_cfg")"
  mono_prefix="$(jq -r 'if .monorepo.enabled then (.monorepo.agent_prefix // "") else "" end' <<< "$repo_cfg")"
  cfg_slug="$(jq -r '(.slug // "") | if . == "" then "customer" else . end' <<< "$repo_cfg")"
  df_declared="$(jq -r '.toolchain.dockerfile // ""' <<< "$repo_cfg")"
  tester_df_declared="$(jq -r '.toolchain.tester_dockerfile // ""' <<< "$repo_cfg")"
  # Isolate harness-config name per factory (with origin URL hash when present) whenever a custom Dockerfile
  # is declared so sibling factories or distinct repos sharing 1 Hub never overwrite shared images (H2, M10).
  if [[ -n "$df_declared" || -n "$tester_df_declared" ]]; then
    hc_prefix="${pack_prefix}-${cfg_slug}"
    if [[ -n "$mono_prefix" && "$mono_prefix" != "$pack_prefix" ]]; then
      hc_prefix="${hc_prefix}-${mono_prefix}"
    fi
    if [[ -n "$TARGET_REPO" ]] && command -v git >/dev/null 2>&1 && git -C "$TARGET_REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      origin_url="$(git -C "$TARGET_REPO" remote get-url origin 2>/dev/null || true)"
    fi
    if [[ -n "$origin_url" ]]; then
      origin_hash="$(printf '%s' "$origin_url" | python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.read().strip().encode()).hexdigest()[:6])')"
      hc_prefix="${hc_prefix}-${origin_hash}"
    fi
    if [[ "$hc_prefix" == "$pack_prefix" ]]; then
      echo "APPLY FAILED: Custom Dockerfile resolved to shared pack harness prefix '${pack_prefix}'." >&2
      exit 1
    fi
  fi
  if [[ -n "$LANDING_ZONE_JSON" && -f "$LANDING_ZONE_JSON" ]]; then
    inf_proj="$(jq -r '.inference_project_id.value // empty' "$LANDING_ZONE_JSON")"
  fi

  if [[ -d "$KIT_DIR/harness-configs" ]]; then
    # Stage harness configs in project-local .scion/ with --scope global whenever the repo is linked
    # so stale ~/.scion/harness-configs from another factory never leak across Hubs (HC13-F6).
    local global_hc_root="${HOME}/.scion/harness-configs"
    local hc_sync_flags=(--global)
    if [[ -n "$TARGET_REPO" && -d "$TARGET_REPO/.scion" ]]; then
      global_hc_root="${TARGET_REPO}/.scion/harness-configs"
      hc_sync_flags=(--scope global)
    fi
    mkdir -p "$global_hc_root"
    for hc_dir in "$KIT_DIR"/harness-configs/*; do
      [[ -d "$hc_dir" && -f "$hc_dir/config.yaml" ]] || continue
      local src_hc_name hc_name img_override=""
      src_hc_name="$(basename "$hc_dir")"
      hc_name="${hc_prefix}-${src_hc_name#"${pack_prefix}-"}"
      if [[ "$src_hc_name" == *"-claude-vertex" && "$claude_mg_enabled" != "true" ]]; then
        echo "SKIP harness-config: $hc_name (harnesses.claude_model_garden_enabled=false; using Vertex AI Gemini 1P)."
        continue
      fi
      if [[ "$src_hc_name" == *"-claude-vertex" ]]; then
        img_override="$HARNESS_IMAGE_CLAUDE"
        echo "VERTEX MODEL GARDEN CHECKPOINT: confirm claude-opus-5-5 is manually enabled at https://console.cloud.google.com/vertex-ai/publishers/anthropic/model-garden/claude-opus-5-5?project=${inf_proj:-YOUR_INFERENCE_PROJECT} (region=${claude_reg})."
      elif [[ "$src_hc_name" == *"-antigravity-vertex" ]]; then
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
      if [[ -n "$TARGET_REPO" && -d "$TARGET_REPO/.scion" ]]; then
        hc_out="$(cd "$TARGET_REPO" && scion harness-config sync "$hc_name" "${hc_sync_flags[@]}" --hub "$HUB_URL" 2>&1)" || hc_rc=$?
      else
        hc_out="$(scion harness-config sync "$hc_name" "${hc_sync_flags[@]}" --hub "$HUB_URL" 2>&1)" || hc_rc=$?
      fi
      if [[ "$hc_rc" -eq 0 ]]; then
        printf '%s\n' "$hc_out"
      elif grep -qiE '409|conflict|already exists' <<< "$hc_out"; then
        sleep 2
        if [[ -n "$TARGET_REPO" && -d "$TARGET_REPO/.scion" ]]; then
          (cd "$TARGET_REPO" && scion harness-config sync "$hc_name" "${hc_sync_flags[@]}" --hub "$HUB_URL")
        else
          scion harness-config sync "$hc_name" "${hc_sync_flags[@]}" --hub "$HUB_URL"
        fi
      else
        printf '%s\n' "$hc_out" >&2
        return "$hc_rc"
      fi
    done
    # Sync dedicated heavy tester harness-config when toolchain.tester_dockerfile built HARNESS_IMAGE_TESTER (H2).
    if [[ -n "$HARNESS_IMAGE_TESTER" && -f "$KIT_DIR/harness-configs/${pack_prefix}-antigravity-vertex/config.yaml" ]]; then
      local tester_hc_name="${hc_prefix}-tester-antigravity-vertex"
      local tester_src="$KIT_DIR/harness-configs/${pack_prefix}-antigravity-vertex"
      rm -rf "${global_hc_root:?}/${tester_hc_name}"
      local tester_base_args=()
      if scion harness-config pull "antigravity" --to "${global_hc_root}/${tester_hc_name}" --hub "$HUB_URL" >/dev/null 2>&1; then
        tester_base_args=(--base-harness-yaml "${global_hc_root}/${tester_hc_name}/config.yaml")
      else
        cp -r "$tester_src" "${global_hc_root}/${tester_hc_name}"
      fi
      python3 "$SCRIPT_DIR/parse_hub_project.py" \
        --render-harness-src "$tester_src/config.yaml" \
        --render-harness-dst "${global_hc_root}/${tester_hc_name}/config.yaml" \
        "${tester_base_args[@]}" \
        --inference-project "$inf_proj" \
        --gemini-location "$gemini_loc" \
        --claude-region "$claude_reg" \
        --pin-image "$HARNESS_IMAGE_TESTER"
      if [[ -n "$TARGET_REPO" && -d "$TARGET_REPO/.scion" ]]; then
        (cd "$TARGET_REPO" && scion harness-config sync "$tester_hc_name" "${hc_sync_flags[@]}" --hub "$HUB_URL")
      else
        scion harness-config sync "$tester_hc_name" "${hc_sync_flags[@]}" --hub "$HUB_URL"
      fi
      echo "SYNCED TESTER HARNESS-CONFIG: ${tester_hc_name}"
    fi
    # Never overwrite Hub-global default_harness_config on shared Hubs or when using a per-factory custom image (H4, M10).
    if [[ "$existing_hub" == "true" || "$hc_prefix" != "$pack_prefix" ]]; then
      echo "SKIP hub-global default_harness_config update (existing_hub=${existing_hub}, hc_prefix=${hc_prefix}; agents pass --harness-config explicitly)."
    else
      scion hub settings set default_harness_config "${hc_prefix}-${default_harness}" --hub "$HUB_URL"
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

  # 5. Apply Hub-global security, FinOps, and telemetry settings ONLY on dedicated Hubs (existing_hub=false, H4).
  # Shared Hubs manage these once via Phase A `bootstrap-hub-project.sh platform-init`.
  if [[ "$existing_hub" == "true" ]]; then
    echo "SKIP Hub-global settings, experiments, and telemetry updates (existing_hub=true; managed once via platform-init)."
  else
    apply_hub_global_governance "$max_dur" "$max_turns" "$max_calls" "$auto_susp"
  fi

  # Set project-scope Vertex AI env vars (--always) via native Scion CLI (fallback to REST PUT only if CLI lacks --always)
  # so container-side harness provisioners receive inference_project_id across Lite VM and GKE topologies (HC-01 F24, HC-02 F8).
  if [[ -n "$inf_proj" ]]; then
    local proj_id="${resolved_proj_id:-}"
    if [[ -z "$proj_id" && -n "$PROJECT_SLUG" ]]; then
      proj_id="$(resolve_project_id)"
    fi
    local env_target="${PROJECT_SLUG:-$proj_id}"
    if [[ -n "$env_target" ]]; then
      local kv k v
      for kv in "GOOGLE_CLOUD_PROJECT=${inf_proj}" "GOOGLE_CLOUD_QUOTA_PROJECT=${inf_proj}" "GOOGLE_CLOUD_LOCATION=${gemini_loc}" "GOOGLE_GENAI_USE_VERTEXAI=true" "AGY_ADC_AUTH=true"; do
        k="${kv%%=*}"; v="${kv#*=}"
        if scion hub env set --project="$env_target" --always "${k}=${v}" --hub "$HUB_URL" >/dev/null 2>&1; then
          echo "SET PROJECT ENV: ${k}=${v}"
        elif [[ -n "$proj_id" && -n "${SCION_HUB_TOKEN:-}" ]]; then
          curl -sf -X PUT \
            -H "Authorization: Bearer ${SCION_HUB_TOKEN}" \
            -H "Content-Type: application/json" \
            "${HUB_URL%/}/api/v1/projects/${proj_id}/env/${k}" \
            -d "{\"value\":\"${v}\",\"injectionMode\":\"always\"}" >/dev/null \
            && echo "SET PROJECT ENV: ${k}=${v}" \
            || echo "WARNING: Failed to set project env ${k} via REST fallback." >&2
        else
          echo "WARNING: Failed to set project env ${k} via 'scion hub env set' and SCION_HUB_TOKEN is unset for REST fallback." >&2
        fi
      done
    fi
    if [[ -n "$proj_id" ]]; then
      warn_github_token_injection_mode "$proj_id"
      ensure_delta_watcher_hub_rbac "$proj_id"
    fi
  fi

  if [[ -n "$TARGET_REPO" ]]; then
    do_overlay_sync
  fi
  # Start Coordinator before scheduling recurring messages targeting it (Scion v0.4.0-preview.4 validates agent existence, HC13-F4).
  ensure_coordinator_started "$pack_prefix" "$default_harness" "$repo_cfg" "${coord_sa:-$worker_sa}" "$hc_prefix"

  # 6. Schedule daily closed-loop Kaizen by default on every project (sibling-safe in monorepos/shared Hubs, H3).
  ensure_kaizen_schedule \
    "$pack_prefix" \
    "$(jq -re '.kaizen.enabled | tostring' <<< "$repo_cfg")" \
    "$(jq -re '.kaizen.schedule_cron' <<< "$repo_cfg")" \
    "$(jq -re '.kaizen.time_zone' <<< "$repo_cfg")" \
    "$(jq -re '.kaizen.coordinator_agent' <<< "$repo_cfg")" \
    "$(jq -r '(.kaizen.enable_gcp_obs // false) | tostring' <<< "$repo_cfg")" \
    "$existing_hub" \
    "$mono_enabled"
  warn_adk_ge_license_preflight "$pack_name"
  print_github_ci_variables "$pack_name"
  print_delta_watcher_alignment "$repo_cfg" "$pack_prefix" "${resolved_proj_id:-}"
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
  platform-init) do_platform_init ;;
  preflight) do_preflight ;;
  plan) do_plan ;;
  backup) do_backup ;;
  apply) do_apply ;;
  overlay-sync) do_overlay_sync ;;
  rollback) do_rollback ;;
  *) usage ;;
esac
