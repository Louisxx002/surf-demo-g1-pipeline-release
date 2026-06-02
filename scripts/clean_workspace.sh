#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS_ROOT="${DEPS_ROOT:-${WORKSPACE_ROOT}/deps}"
SURF_ROOT="${SURF_ROOT:-${DEPS_ROOT}/SURF2026_VoiceModule-main}"

clean_runtime=0
clean_logs=0

for arg in "$@"; do
  case "$arg" in
    --runtime) clean_runtime=1 ;;
    --logs) clean_logs=1 ;;
    -h|--help)
      cat <<'USAGE'
Usage: scripts/clean_workspace.sh [--runtime] [--logs]

Default:
  Remove Python and pytest caches from the integrated workspace and SURF module.

Options:
  --runtime  Remove generated runtime files such as tts.wav/status JSON.
  --logs     Remove per-session logs under logs/.
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

echo "Cleaning Python caches..."
find "${WORKSPACE_ROOT}" "${SURF_ROOT}" \
  -type d \( -name __pycache__ -o -name .pytest_cache \) \
  -prune -exec rm -rf {} +

find "${WORKSPACE_ROOT}" "${SURF_ROOT}" \
  -type f \( -name '*.pyc' -o -name '*.pyo' \) \
  -delete

if [[ "$clean_runtime" == "1" ]]; then
  echo "Cleaning generated runtime files..."
  find "${WORKSPACE_ROOT}/runtime" -mindepth 1 ! -name .gitkeep -exec rm -rf {} +
  mkdir -p "${WORKSPACE_ROOT}/runtime"
  touch "${WORKSPACE_ROOT}/runtime/.gitkeep"
fi

if [[ "$clean_logs" == "1" ]]; then
  echo "Cleaning session logs..."
  rm -rf "${WORKSPACE_ROOT}/logs"
  mkdir -p "${WORKSPACE_ROOT}/logs"
fi

echo "Clean complete."
