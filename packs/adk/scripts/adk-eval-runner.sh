#!/usr/bin/env bash
# Thin lock-guarded wrapper for packs/adk Level 1 and Level 2 verification.
# Serializes per-PR Sandbox executions via flock and delegates logic to adk_sandbox_gate.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK_DIR="${ADK_LOCK_DIR:-/tmp/adk-sandbox-locks}"
mkdir -p "$LOCK_DIR"

PR_NUM="default"
for ((i=1; i<=$#; i++)); do
  if [[ "${!i}" == "--pr-number" ]]; then
    next=$((i+1))
    PR_NUM="${!next:-default}"
  fi
done

exec flock "${LOCK_DIR}/pr-${PR_NUM}.lock" python3 "${SCRIPT_DIR}/adk_sandbox_gate.py" "$@"
