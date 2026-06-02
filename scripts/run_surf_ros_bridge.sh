#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_ROOT}"

set -a
source "${WORKSPACE_ROOT}/config/default.env"
set +a

export PYTHONPATH="${WORKSPACE_ROOT}:${PYTHONPATH:-}"
export ROS_LOG_DIR="${WORKSPACE_ROOT}/runtime/ros_logs"
export SURF_BRIDGE_HOST="${SURF_BRIDGE_HOST:-127.0.0.1}"
export SURF_BRIDGE_PORT="${SURF_BRIDGE_PORT:-18765}"
mkdir -p "${ROS_LOG_DIR}"

set +u
source /opt/ros/jazzy/setup.bash
set -u

exec python3 surf_ros_bridge.py
