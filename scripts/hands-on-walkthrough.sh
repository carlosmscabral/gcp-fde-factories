#!/usr/bin/env bash
# Interactive didactic runner for gcp-fde-factories (packs/gecx and packs/adk).
# Walks an engineer step-by-step through every stage of the factory, explaining WHY
# each command runs before executing it. Passes --configuration only when requested.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STEP="all"
PACK="gecx"
GCLOUD_CONFIG=""
HUB_PROJECT=""
HUB_VM=""
HUB_ZONE="us-central1-a"
KIT_OUT=""

usage() {
  cat <<'EOF'
Usage: scripts/hands-on-walkthrough.sh [--pack gecx|adk] [--step 1|2|3|4|5|6|all] \
  [--gcloud-config <name>] [--hub-project <project-id>] [--hub-vm <vm-name>] [--zone <zone>]

Steps (safe, read/build-focused local and GCP verification steps):
  1  Validate pack schemas, SHA-40 skills.lock, Layer 0+1+2 context budget, and clean-room sanitizer
  2  Run the full offline unit test suite (anti-forgery Verdict, Kaizen, Brownfield, ADK/GE, IAM)
  3  Build a self-contained offline Release Kit and inspect generated templates and skills
  4  Validate all 3 Terraform deployment stages (01-landing-zone, lite-vm, ha-gke)
  5  Verify CLI and API contract canaries against pinned snapshots
  6  Inspect live Hub VM health over IAP SSH (requires --hub-project and --hub-vm)
EOF
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pack) PACK="$2"; shift 2 ;;
    --step) STEP="$2"; shift 2 ;;
    --gcloud-config) GCLOUD_CONFIG="$2"; shift 2 ;;
    --hub-project) HUB_PROJECT="$2"; shift 2 ;;
    --hub-vm) HUB_VM="$2"; shift 2 ;;
    --zone) HUB_ZONE="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown flag: $1" >&2; usage ;;
  esac
done

KIT_OUT="${KIT_OUT:-/tmp/${PACK}-kit-handson}"

pause_step() {
  local title="$1" why="$2"
  echo ""
  echo "========================================================================"
  echo "  $title"
  echo "  WHY: $why"
  echo "========================================================================"
  if [[ -t 0 ]]; then
    read -r -p "Press Enter to run this step (Ctrl+C to stop)... "
  fi
}

step_1() {
  pause_step "STEP 1: Static Catalog Gate (./build.sh --check packs/${PACK})" \
    "Proves pack.yaml, compat.yaml, skills.lock (SHA-40), total context budget (0+1+2), 90d TTL, and public clean-room rules pass before any deploy."
  cd "$REPO_ROOT"
  ./build.sh --check "packs/${PACK}"
}

step_2() {
  pause_step "STEP 2: Deterministic Unit Test Suite (./build.sh --test)" \
    "Proves negative security guards (forged Verdict, Kaizen verifier, Brownfield drift, ADK/GE export, IAM least privilege) pass offline."
  cd "$REPO_ROOT"
  ./build.sh --test
}

step_3() {
  pause_step "STEP 3: Build Offline Release Kit (./build.sh --release-kit)" \
    "Composes prefix-isolated templates (zero external URIs, zero hardcoded models) and Hub Skill Bank directories into $KIT_OUT."
  cd "$REPO_ROOT"
  ./build.sh --release-kit "packs/${PACK}" --out "$KIT_OUT"
  echo "--- Generated templates (notice ${PACK}- prefix, no model key) ---"
  ls -1 "$KIT_OUT/templates"
  echo "--- Sample ${PACK}-deployer/scion-agent.yaml ---"
  cat "$KIT_OUT/templates/${PACK}-deployer/scion-agent.yaml"
  echo "--- Generated manifest.json summary ---"
  jq '{pack, pack_version, scion_tested, external_uris_remaining, templates: [.templates[].name], skills: [.skills[].name]}' "$KIT_OUT/manifest.json"
}

step_4() {
  pause_step "STEP 4: Validate 3-Stage Repeatable Terraform" \
    "Confirms Stage 01 (Landing Zone) and Stage 02 (lite-vm + ha-gke) HCL syntax and variable contracts are valid."
  for tfdir in deploy/01-landing-zone deploy/02-factory-runtime/lite-vm deploy/02-factory-runtime/ha-gke; do
    echo "--- terraform validate: $tfdir ---"
    terraform -chdir="$REPO_ROOT/$tfdir" init -backend=false -input=false -no-color >/dev/null
    terraform -chdir="$REPO_ROOT/$tfdir" validate -no-color
  done
}

step_5() {
  pause_step "STEP 5: Contract Canaries (GECX CLI + ADK GE Export)" \
    "Verifies pinned CLI and API contract snapshots so upstream drift breaks the PR instead of breaking production."
  "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/canaries/gecx/check_cli_contract.py"
  "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/canaries/adk/check_ge_contract.py"
}

step_6() {
  if [[ -z "$HUB_PROJECT" || -z "$HUB_VM" ]]; then
    echo "Skipping Step 6 (pass --hub-project <id> --hub-vm <name> to inspect a live Hub VM via IAP SSH)."
    return 0
  fi
  pause_step "STEP 6: Live Read-Only Check on Hub VM (via IAP SSH)" \
    "Connects through IAP TCP forwarding (zero public IP) to inspect live Scion v0.4.0-preview.3 health and hardened settings.yaml."
  GCLOUD_ARGS=()
  if [[ -n "$GCLOUD_CONFIG" ]]; then
    GCLOUD_ARGS=(--configuration="$GCLOUD_CONFIG")
  fi
  gcloud "${GCLOUD_ARGS[@]}" compute ssh "$HUB_VM" \
    --project="$HUB_PROJECT" --zone="$HUB_ZONE" --tunnel-through-iap \
    --command="curl -fsS http://127.0.0.1:8080/healthz | jq . && echo '=== Settings YAML ===' && sudo cat /home/scion/.scion/settings.yaml"
}

case "$STEP" in
  1) step_1 ;;
  2) step_2 ;;
  3) step_3 ;;
  4) step_4 ;;
  5) step_5 ;;
  6) step_6 ;;
  all) step_1; step_2; step_3; step_4; step_5; step_6 ;;
  *) usage ;;
esac
