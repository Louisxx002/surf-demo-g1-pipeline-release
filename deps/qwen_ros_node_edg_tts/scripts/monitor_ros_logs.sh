#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/runtime/ros_logs"

mkdir -p "${LOG_DIR}"
echo "Monitoring qwen_audio_node logs in ${LOG_DIR}. Press Ctrl+C to stop."
tail -n 80 -F "${LOG_DIR}"/*.log
