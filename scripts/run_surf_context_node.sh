#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_ROOT}"

set -a
source "${WORKSPACE_ROOT}/config/default.env"
set +a

export QWEN_RUNTIME_DIR="${WORKSPACE_ROOT}/runtime"
export PYTHONPATH="${WORKSPACE_ROOT}:${QWEN_ROOT}/third_party/unitree_sdk2_python:${PYTHONPATH:-}"
export ROS_LOG_DIR="${WORKSPACE_ROOT}/runtime/ros_logs"
export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"
mkdir -p "${QWEN_RUNTIME_DIR}" "${ROS_LOG_DIR}"

set +u
source /opt/ros/jazzy/setup.bash
set -u

exec "${QWEN_PYTHON}" qwen_surf_context_node.py
