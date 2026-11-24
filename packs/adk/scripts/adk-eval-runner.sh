#!/usr/bin/env bash
# Thin lock-guarded wrapper for packs/adk Level 1 and Level 2 verification.
# Supports both `--pr-number N` and `--pr-number=N`, rejects non-numeric keys, and enforces flock -w 300.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_LOCK_DIR="/tmp/adk-sandbox-locks"
if [[ -d "/scion-volumes/scratchpad" && -w "/scion-volumes/scratchpad" ]]; then
  DEFAULT_LOCK_DIR="/scion-volumes/scratchpad/locks"
fi
LOCK_DIR="${ADK_LOCK_DIR:-$DEFAULT_LOCK_DIR}"
mkdir -p "$LOCK_DIR"

PR_NUM=""
for ((i=1; i<=$#; i++)); do
  arg="${!i}"
  if [[ "$arg" == "--pr-number" ]]; then
    next=$((i+1))
    PR_NUM="${!next:-}"
  elif [[ "$arg" == --pr-number=* ]]; then
    PR_NUM="${arg#--pr-number=}"
  fi
done

if [[ -n "$PR_NUM" && ! "$PR_NUM" =~ ^[0-9]+$ ]]; then
  echo "Invalid --pr-number '${PR_NUM}': must contain digits only." >&2
  exit 2
fi
LOCK_KEY="${PR_NUM:-default}"

exec 9>"${LOCK_DIR}/adk-pr-${LOCK_KEY}.lock"
if ! flock -w 300 9; then
  echo "Failed to acquire ADK Sandbox lock for PR '${LOCK_KEY}' within 300s." >&2
  exit 1
fi

exec python3 "${SCRIPT_DIR}/adk_sandbox_gate.py" "$@"
