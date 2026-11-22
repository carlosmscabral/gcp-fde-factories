#!/usr/bin/env bash
# Contract 4 thin entrypoint for GECX split-SA Level 1 + Level 2 Sandbox verification.
# Acquires a per-PR file lock to prevent draft collisions, records a ledger entry,
# and delegates execution to gecx_sandbox_gate.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PR_NUMBER=""
LOCK_DIR="${SCION_SCRATCHPAD_DIR:-/tmp/gecx-scratchpad}/locks"
LEDGER_FILE="${SCION_SCRATCHPAD_DIR:-/tmp/gecx-scratchpad}/sandbox-ledger.jsonl"

for ((i=1; i<=$#; i++)); do
  if [[ "${!i}" == "--pr-number" ]]; then
    next=$((i + 1))
    PR_NUMBER="${!next}"
  fi
done

if [[ -z "$PR_NUMBER" ]]; then
  echo "Usage: gecx-eval-runner.sh --pr-number <N> [options passed to gecx_sandbox_gate.py]" >&2
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
