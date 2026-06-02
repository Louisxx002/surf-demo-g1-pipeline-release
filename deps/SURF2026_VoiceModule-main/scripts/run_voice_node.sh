#!/usr/bin/env bash
# Start voice_pipeline_node as a systemd user service.
# Usage: ./scripts/run_voice_node.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

set -a
source "${PROJECT_ROOT}/config/default.env"
set +a

export VOICE_RUNTIME_DIR="${PROJECT_ROOT}/runtime"
export ROS_LOG_DIR="${PROJECT_ROOT}/runtime/ros_logs"
mkdir -p "${VOICE_RUNTIME_DIR}" "${ROS_LOG_DIR}"

systemctl --user stop voice-pipeline.service >/dev/null 2>&1 || true

systemd-run --user --unit=voice-pipeline --same-dir --collect \
  --setenv=HF_HUB_OFFLINE=1 \
  --setenv=UNITREE_DOMAIN_ID="${UNITREE_DOMAIN_ID}" \
  --setenv=UNITREE_NETWORK_INTERFACE="${UNITREE_NETWORK_INTERFACE}" \
  "${PROJECT_ROOT}/run_node.sh"

echo "voice-pipeline.service started."
echo "Logs: journalctl --user -u voice-pipeline -f"
