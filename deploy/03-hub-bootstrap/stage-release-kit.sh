#!/usr/bin/env bash
# Stages a Release Kit into a customer Artifact Registry using rebuild (default) or crane mirror mode.
# Uses crane/gcrane for digest-preserving OCI mirror copies (gcloud artifacts docker images copy does not exist).
set -euo pipefail

MODE="rebuild"
KIT_DIR=""
LANDING_ZONE_JSON=""
GCLOUD_CONFIG=""
DRY_RUN="false"

usage() {
  cat <<'EOF'
Usage: stage-release-kit.sh --kit <release-kit-dir> --landing-zone <landing-zone-outputs.json> \
  [--mode rebuild|mirror] [--gcloud-config <name>] [--dry-run]
EOF
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --kit) KIT_DIR="$2"; shift 2 ;;
    --landing-zone) LANDING_ZONE_JSON="$2"; shift 2 ;;
    --gcloud-config) GCLOUD_CONFIG="$2"; shift 2 ;;
    --dry-run) DRY_RUN="true"; shift 1 ;;
    *) echo "Unknown flag: $1" >&2; usage ;;
  esac
done

[[ -n "$KIT_DIR" && -n "$LANDING_ZONE_JSON" ]] || usage
command -v jq >/dev/null 2>&1 || { echo "Missing required CLI: jq" >&2; exit 1; }

AR_URL="$(jq -re '.artifact_registry_url.value' "$LANDING_ZONE_JSON")"
HUB_PROJECT="$(jq -re '.hub_project_id.value' "$LANDING_ZONE_JSON")"
REGION="$(jq -re '.region.value' "$LANDING_ZONE_JSON")"
PACK_NAME="$(jq -re '.pack' "$KIT_DIR/manifest.json")"
PACK_VERSION="$(jq -re '.pack_version' "$KIT_DIR/manifest.json")"

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
      if [[ "$COPY_TOOL" == "crane" ]]; then
        run_or_echo crane copy "$src_ref" "$target_ref"
        if [[ "$DRY_RUN" != "true" ]]; then
          src_digest="${src_ref##*@}"
          dst_digest="$(crane digest "$target_ref")"
          [[ "$dst_digest" == "$src_digest" ]] || { echo "DIGEST MISMATCH: expected $src_digest, got $dst_digest" >&2; exit 1; }
        fi
      else
        run_or_echo gcrane cp "$src_ref" "$target_ref"
      fi
    done < <(jq -r '.images | to_entries[] | [.key, .value] | @tsv' "$KIT_DIR/manifest.json")
    ;;
  rebuild)
    echo "=== Staging Release Kit (${PACK_NAME}@${PACK_VERSION}) via internal Cloud Build rebuild -> $AR_URL ==="
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BUILDER_SA="$(jq -r '.release_builder_sa_email.value // empty' "$LANDING_ZONE_JSON")"
    SA_ARGS=()
    if [[ -n "$BUILDER_SA" ]]; then
      SA_ARGS=(--service-account="projects/${HUB_PROJECT}/serviceAccounts/${BUILDER_SA}")
    fi
    run_or_echo gcloud "${GCLOUD_ARGS[@]}" builds submit "$KIT_DIR" \
      --project="$HUB_PROJECT" \
      --region="$REGION" \
      "${SA_ARGS[@]}" \
      --config="$SCRIPT_DIR/cloudbuild.yaml" \
      --substitutions="_AR_URL=${AR_URL},_PACK=${PACK_NAME},_PACK_VERSION=${PACK_VERSION}"
    ;;
  *)
    echo "Invalid --mode '$MODE'. Use rebuild or mirror." >&2
    exit 2
    ;;
esac
