#!/usr/bin/env bash
# Stages a Release Kit into a customer Artifact Registry using rebuild (default) or crane mirror mode.
# Captures pushed immutable @sha256 digests and stamps them into manifest.json and harness-configs/*/config.yaml.
set -euo pipefail

MODE="rebuild"
KIT_DIR=""
LANDING_ZONE_JSON=""
GCLOUD_CONFIG=""
BASE_IMAGE="python:3.12-slim-bookworm"
ANTIGRAVITY_BASE_IMAGE=""
CLAUDE_BASE_IMAGE=""
CORE_VERSION="0.5.0"
DRY_RUN="false"

usage() {
  cat <<'EOF'
Usage: stage-release-kit.sh --kit <release-kit-dir> --landing-zone <landing-zone-outputs.json> \
  [--mode rebuild|mirror] [--base-image <ci-base-ref>] \
  [--antigravity-base-image <scion-antigravity-base>] [--claude-base-image <scion-claude-base>] \
  [--core-version <semver>] [--gcloud-config <name>] [--dry-run]
EOF
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --kit) KIT_DIR="$2"; shift 2 ;;
    --landing-zone) LANDING_ZONE_JSON="$2"; shift 2 ;;
    --base-image) BASE_IMAGE="$2"; shift 2 ;;
    --antigravity-base-image) ANTIGRAVITY_BASE_IMAGE="$2"; shift 2 ;;
    --claude-base-image) CLAUDE_BASE_IMAGE="$2"; shift 2 ;;
    --core-version) CORE_VERSION="$2"; shift 2 ;;
    --gcloud-config) GCLOUD_CONFIG="$2"; shift 2 ;;
    --dry-run) DRY_RUN="true"; shift 1 ;;
    *) echo "Unknown flag: $1" >&2; usage ;;
  esac
done

[[ -n "$KIT_DIR" && -n "$LANDING_ZONE_JSON" ]] || usage
command -v jq >/dev/null 2>&1 || { echo "Missing required CLI: jq" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AR_URL="$(jq -re '.artifact_registry_url.value' "$LANDING_ZONE_JSON")"
HUB_PROJECT="$(jq -re '.hub_project_id.value' "$LANDING_ZONE_JSON")"
REGION="$(jq -re '.region.value' "$LANDING_ZONE_JSON")"
PACK_NAME="$(jq -re '.pack' "$KIT_DIR/manifest.json")"
PACK_PREFIX="$(jq -re '.pack_prefix // .pack' "$KIT_DIR/manifest.json")"
PACK_VERSION="$(jq -re '.pack_version' "$KIT_DIR/manifest.json")"
PACK_DOCKERFILE="packs/${PACK_NAME}/Dockerfile"
if [[ ! -f "$KIT_DIR/$PACK_DOCKERFILE" ]]; then
  PACK_DOCKERFILE="$(cd "$KIT_DIR" && find packs -maxdepth 2 -name Dockerfile | head -n 1)"
fi

GCLOUD_ARGS=()
if [[ -n "$GCLOUD_CONFIG" ]]; then
  GCLOUD_ARGS=(--configuration="$GCLOUD_CONFIG")
fi

run_or_echo() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] $*"
  else
    "$@"
  fi
}

stamp_manifest_and_harness() {
  local img_key="$1" pinned_ref="$2" hc_suffix="${3:-}"
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] stamp manifest.json .images[\"${img_key}\"] = ${pinned_ref}"
    return 0
  fi
  local tmp_m
  tmp_m="$(mktemp)"
  jq --arg k "$img_key" --arg v "$pinned_ref" '.images[$k] = $v' "$KIT_DIR/manifest.json" > "$tmp_m"
  mv "$tmp_m" "$KIT_DIR/manifest.json"
  if [[ -n "$hc_suffix" ]]; then
    local hc_cfg="$KIT_DIR/harness-configs/${PACK_PREFIX}-${hc_suffix}/config.yaml"
    if [[ -f "$hc_cfg" ]]; then
      python3 - "$hc_cfg" "$pinned_ref" <<'PY'
import pathlib, sys, yaml
p = pathlib.Path(sys.argv[1])
data = yaml.safe_load(p.read_text(encoding="utf-8"))
data["image"] = sys.argv[2]
p.write_text(yaml.safe_dump(data, sort_keys=False, width=120), encoding="utf-8")
PY
      echo "STAMPED HARNESS IMAGE: $hc_cfg -> $pinned_ref"
    fi
  fi
}

submit_and_stamp() {
  local base_img="$1" core_img_name="$2" target_img_name="$3" hc_suffix="${4:-}" final_user="${5:-scion}"
  local builder_sa staging_bkt sa_args=() staging_args=()
  builder_sa="$(jq -r '.release_builder_sa_email.value // empty' "$LANDING_ZONE_JSON")"
  if [[ -n "$builder_sa" ]]; then
    sa_args=(--service-account="projects/${HUB_PROJECT}/serviceAccounts/${builder_sa}")
  fi
  # Route Cloud Build source staging to the Landing Zone bucket to avoid concurrent races
  # on auto-created <hub>_cloudbuild buckets in brand-new projects (HC-03 F1).
  # Omit --gcs-log-dir because cloudbuild.yaml enforces options.logging: CLOUD_LOGGING_ONLY (HC-04 F4).
  staging_bkt="$(jq -r '.sandbox_staging_bucket.value // empty' "$LANDING_ZONE_JSON")"
  if [[ -n "$staging_bkt" ]]; then
    staging_args=(
      --gcs-source-staging-dir="gs://${staging_bkt}/release-kit-src/${PACK_NAME}-${target_img_name}"
    )
  fi
  run_or_echo gcloud "${GCLOUD_ARGS[@]}" builds submit "$KIT_DIR" \
    --project="$HUB_PROJECT" \
    --region="$REGION" \
    "${sa_args[@]}" \
    "${staging_args[@]}" \
    --config="$SCRIPT_DIR/cloudbuild.yaml" \
    --substitutions="_AR_URL=${AR_URL},_BASE_IMAGE=${base_img},_CORE_VERSION=${CORE_VERSION},_PACK_VERSION=${PACK_VERSION},_CORE_IMAGE_NAME=${core_img_name},_IMAGE_NAME=${target_img_name},_DOCKERFILE=${PACK_DOCKERFILE},_FINAL_USER=${final_user}"
  if [[ "$DRY_RUN" != "true" ]]; then
    local digest pinned_ref core_digest
    digest="$(gcloud "${GCLOUD_ARGS[@]}" artifacts docker images describe \
      "${AR_URL}/${target_img_name}:${PACK_VERSION}" \
      --project="$HUB_PROJECT" --format='value(image_summary.digest)')"
    [[ "$digest" == sha256:* ]] || { echo "Failed to resolve pushed digest for ${target_img_name}:${PACK_VERSION}" >&2; exit 1; }
    pinned_ref="${AR_URL}/${target_img_name}@${digest}"
    stamp_manifest_and_harness "$target_img_name" "$pinned_ref" "$hc_suffix"
    if [[ "$core_img_name" == "core-gcp-fde-base" ]]; then
      core_digest="$(gcloud "${GCLOUD_ARGS[@]}" artifacts docker images describe \
        "${AR_URL}/${core_img_name}:${CORE_VERSION}" \
        --project="$HUB_PROJECT" --format='value(image_summary.digest)' 2>/dev/null || true)"
      if [[ "$core_digest" == sha256:* ]]; then
        stamp_manifest_and_harness "$core_img_name" "${AR_URL}/${core_img_name}@${core_digest}" ""
      fi
    fi
  fi
}

case "$MODE" in
  mirror)
    echo "=== Staging Release Kit (${PACK_NAME}@${PACK_VERSION}) via digest-verified OCI mirror -> $AR_URL ==="
    jq -e --arg key "${PACK_NAME}-runtime" '.images | has($key) or has("scion-" + $key)' "$KIT_DIR/manifest.json" >/dev/null \
      || { echo "MIRROR FAILED: manifest.json images lacks runtime digest for pack '${PACK_NAME}'." >&2; exit 1; }

    COPY_TOOL="crane"
    if [[ "$DRY_RUN" != "true" ]]; then
      if command -v crane >/dev/null 2>&1; then
        COPY_TOOL="crane"
      elif command -v gcrane >/dev/null 2>&1; then
        COPY_TOOL="gcrane"
      else
        echo "MIRROR FAILED: install 'crane' or 'gcrane' for OCI digest copies, or use --mode rebuild." >&2
        exit 1
      fi
    fi

    while IFS=$'\t' read -r img_key src_ref; do
      [[ "$src_ref" == *"@sha256:"* ]] || { echo "MIRROR FAILED: source image '${src_ref}' is not digest-pinned." >&2; exit 1; }
      if [[ "$src_ref" == *"REPLACE_HUB_PROJECT"* || "$src_ref" == *"@sha256:0000000000000000000000000000000000000000000000000000000000000000" ]]; then
        echo "MIRROR FAILED: '${img_key}' uses a placeholder reference (${src_ref}). Run with --mode rebuild first." >&2
        exit 1
      fi
      target_ref="${AR_URL}/${img_key}:${PACK_VERSION}"
      src_digest="${src_ref##*@}"
      if [[ "$COPY_TOOL" == "crane" ]]; then
        run_or_echo crane copy "$src_ref" "$target_ref"
        if [[ "$DRY_RUN" != "true" ]]; then
          dst_digest="$(crane digest "$target_ref")"
          [[ "$dst_digest" == "$src_digest" ]] || { echo "DIGEST MISMATCH: expected $src_digest, got $dst_digest" >&2; exit 1; }
        fi
      else
        run_or_echo gcrane cp "$src_ref" "$target_ref"
      fi
      stamp_manifest_and_harness "$img_key" "${AR_URL}/${img_key}@${src_digest}"
    done < <(jq -r '.images | to_entries[] | [.key, .value] | @tsv' "$KIT_DIR/manifest.json")
    ;;
  rebuild)
    echo "=== Staging Release Kit (${PACK_NAME}@${PACK_VERSION}) via internal Cloud Build rebuild -> $AR_URL ==="
    # 1. Always build the lean CI/verification runtime image (<pack>-runtime, non-root scion).
    submit_and_stamp "$BASE_IMAGE" "core-gcp-fde-base" "${PACK_NAME}-runtime" "" "scion"
    # 2. Build Scion agent harness images (USER root preserved so sciontool init PID 1 drops privileges cleanly).
    if [[ -n "$ANTIGRAVITY_BASE_IMAGE" ]]; then
      submit_and_stamp "$ANTIGRAVITY_BASE_IMAGE" "core-gcp-fde-antigravity-base" "${PACK_NAME}-antigravity-runtime" "antigravity-vertex" "root"
    fi
    if [[ -n "$CLAUDE_BASE_IMAGE" ]]; then
      submit_and_stamp "$CLAUDE_BASE_IMAGE" "core-gcp-fde-claude-base" "${PACK_NAME}-claude-runtime" "claude-vertex" "root"
    fi
    if [[ -z "$ANTIGRAVITY_BASE_IMAGE" && -z "$CLAUDE_BASE_IMAGE" ]]; then
      echo "NOTE: Built lean CI runtime image (${PACK_NAME}-runtime) only. Pass --antigravity-base-image / --claude-base-image here, OR pass --harness-image-antigravity / --harness-image-claude to bootstrap-hub-project.sh apply."
    fi
    ;;
  *)
    echo "Invalid --mode '$MODE'. Use rebuild or mirror." >&2
    exit 2
    ;;
esac
