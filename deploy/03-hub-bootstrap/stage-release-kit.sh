#!/usr/bin/env bash
# Stages a Release Kit into a customer Artifact Registry using either mirror or rebuild mode.
# Default mode mirrors digest-pinned pre-built images. Rebuild mode runs Cloud Build inside the customer project.
set -euo pipefail

MODE="mirror"
KIT_DIR=""
LANDING_ZONE_JSON=""
GCLOUD_CONFIG=""
DRY_RUN="false"

usage() {
  cat <<'EOF'
Usage: stage-release-kit.sh --kit <release-kit-dir> --landing-zone <landing-zone-outputs.json> \
  [--mode mirror|rebuild] [--gcloud-config <name>] [--dry-run]
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
AR_URL="$(jq -r '.artifact_registry_url.value' "$LANDING_ZONE_JSON")"
HUB_PROJECT="$(jq -r '.hub_project_id.value' "$LANDING_ZONE_JSON")"
PACK_VERSION="$(jq -r '.pack_version' "$KIT_DIR/manifest.json")"
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
    echo "=== Staging Release Kit ($PACK_VERSION) via pre-built digest mirror -> $AR_URL ==="
    while IFS=$'\t' read -r img_key src_ref; do
      target_ref="${AR_URL}/${img_key}:${PACK_VERSION}"
      run_or_echo gcloud "${GCLOUD_ARGS[@]}" artifacts docker images copy "$src_ref" "$target_ref" --project="$HUB_PROJECT"
    done < <(jq -r '.images | to_entries[] | [.key, .value] | @tsv' "$KIT_DIR/manifest.json")
    ;;
  rebuild)
    echo "=== Staging Release Kit ($PACK_VERSION) via internal Cloud Build rebuild -> $AR_URL ==="
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BUILDER_SA="$(jq -r '.release_builder_sa_email.value // empty' "$LANDING_ZONE_JSON")"
    SA_ARGS=()
    if [[ -n "$BUILDER_SA" ]]; then
      SA_ARGS=(--service-account="projects/${HUB_PROJECT}/serviceAccounts/${BUILDER_SA}")
    fi
    run_or_echo gcloud "${GCLOUD_ARGS[@]}" builds submit "$KIT_DIR" \
      --project="$HUB_PROJECT" \
      --region="$(jq -r '.region.value' "$LANDING_ZONE_JSON")" \
      "${SA_ARGS[@]}" \
      --config="$SCRIPT_DIR/cloudbuild.yaml" \
      --substitutions="_AR_URL=${AR_URL},_PACK_VERSION=${PACK_VERSION}"
    ;;
  *)
    echo "Invalid --mode '$MODE'. Use mirror or rebuild." >&2
    exit 2
    ;;
esac
