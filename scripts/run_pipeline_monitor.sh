#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PIPELINE_MONITOR_PYTHON:-${PYTHON:-python3}}"

cd "${PROJECT_ROOT}"
set -a
# Keep the monitor's robot runtime settings aligned with the pipeline settings.
source "${PROJECT_ROOT}/config/default.env"
set +a
exec "${PYTHON_BIN}" -m pipeline_monitor.server "$@"
