#!/usr/bin/env bash
# Level 2 sandbox verification entrypoint for packs/generic (sw-*).
# Delegates to generic_sandbox_gate.py using commands declared in .factory/factory-profile.yaml.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${1:-.}"
exec python3 "${SCRIPT_DIR}/generic_sandbox_gate.py" --repo "${REPO_DIR}" --level 2
