#!/usr/bin/env bash
# Contract 4 thin entrypoint for GECX split-SA Level 1 + Level 2 Sandbox verification.
# Acquires a per-PR file lock with strict numeric PR validation and delegates to gecx_sandbox_gate.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PR_NUMBER=""
DEFAULT_SCRATCH="/tmp/gecx-scratchpad"
if [[ -d "/scion-volumes/scratchpad" && -w "/scion-volumes/scratchpad" ]]; then
  DEFAULT_SCRATCH="/scion-volumes/scratchpad"
fi
SCRATCH_ROOT="${SCION_SCRATCHPAD_DIR:-$DEFAULT_SCRATCH}"
LOCK_DIR="${SCRATCH_ROOT}/locks"
LEDGER_FILE="${SCRATCH_ROOT}/sandbox-ledger.jsonl"

for ((i=1; i<=$#; i++)); do
  arg="${!i}"
  if [[ "$arg" == "--pr-number" ]]; then
    next=$((i + 1))
    PR_NUMBER="${!next:-}"
  elif [[ "$arg" == --pr-number=* ]]; then
    PR_NUMBER="${arg#--pr-number=}"
  fi
done

if [[ -z "$PR_NUMBER" || ! "$PR_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "Usage: gecx-eval-runner.sh --pr-number <integer> [options passed to gecx_sandbox_gate.py]" >&2
  exit 2
fi

mkdir -p "$LOCK_DIR" "$(dirname "$LEDGER_FILE")"
LOCK_FILE="$LOCK_DIR/pr-${PR_NUMBER}.lock"

exec 9>"$LOCK_FILE"
if ! flock -w 300 9; then
  echo "Failed to acquire Sandbox lock for PR #${PR_NUMBER} within 300 seconds." >&2
  exit 1
fi

export GECX_SANDBOX_LEDGER="$LEDGER_FILE"
exec python3 "$SCRIPT_DIR/gecx_sandbox_gate.py" "$@"
