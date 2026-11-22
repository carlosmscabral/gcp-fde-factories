#!/usr/bin/env bash
# Thin composition root for gcp-fde-factories validation, unit testing, and Release Kit packaging.
# Delegates all logic to modular Python libraries under scripts/lib/.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

usage() {
  cat <<'EOF'
Usage:
  ./build.sh --check <pack-dir>
  ./build.sh --release-kit <pack-dir> --out <output-dir>
  ./build.sh --test
EOF
  exit 2
}

ACTION="${1:-}"
case "$ACTION" in
  --check)
    [[ $# -eq 2 ]] || usage
    exec "$PYTHON_BIN" "$REPO_ROOT/scripts/build.py" check --pack "$2"
    ;;
  --release-kit)
    [[ $# -eq 4 && "$3" == "--out" ]] || usage
    exec "$PYTHON_BIN" "$REPO_ROOT/scripts/build.py" release-kit --pack "$2" --out "$4"
    ;;
  --test)
    exec "$PYTHON_BIN" -m pytest -v "$REPO_ROOT/tests"
    ;;
  *)
    usage
    ;;
esac
