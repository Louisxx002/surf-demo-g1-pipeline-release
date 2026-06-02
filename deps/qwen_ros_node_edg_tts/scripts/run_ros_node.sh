#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

set -a
source "${PROJECT_ROOT}/config/default.env"
set +a
export QWEN_RUNTIME_DIR="${PROJECT_ROOT}/runtime"
export ROS_LOG_DIR="${PROJECT_ROOT}/runtime/ros_logs"
export PYTHONPATH="${PROJECT_ROOT}/third_party/unitree_sdk2_python:${PYTHONPATH:-}"
export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"
mkdir -p "${QWEN_RUNTIME_DIR}" "${ROS_LOG_DIR}"
set +u
source /opt/ros/jazzy/setup.bash
set -u

BRIDGE_PID_FILE="${QWEN_RUNTIME_DIR}/asr_bridge.pid"
BRIDGE_LOG_FILE="${QWEN_RUNTIME_DIR}/asr_bridge.log"

systemctl --user stop qwen-asr-bridge.service >/dev/null 2>&1 || true

start_bridge() {
  if [[ "${QWEN_AUTOSTART_ASR_BRIDGE:-1}" != "1" ]]; then
    return 0
  fi

  if pgrep -f "asr_dds_to_ros_bridge.py --network ${UNITREE_NETWORK_INTERFACE} --domain-id ${UNITREE_DOMAIN_ID} --ros-topic ${QWEN_AUDIO_TOPIC}" >/dev/null 2>&1; then
    return 0
  fi

  nohup "${QWEN_PYTHON}" asr_dds_to_ros_bridge.py \
    --network "${UNITREE_NETWORK_INTERFACE}" \
    --domain-id "${UNITREE_DOMAIN_ID}" \
    --ros-topic "${QWEN_AUDIO_TOPIC}" \
    >"${BRIDGE_LOG_FILE}" 2>&1 &
  echo $! > "${BRIDGE_PID_FILE}"
}

stop_bridge() {
  if [[ -f "${BRIDGE_PID_FILE}" ]]; then
    local bridge_pid
    bridge_pid="$(cat "${BRIDGE_PID_FILE}")"
    if [[ -n "${bridge_pid}" ]] && kill -0 "${bridge_pid}" >/dev/null 2>&1; then
      kill "${bridge_pid}" >/dev/null 2>&1 || true
    fi
    rm -f "${BRIDGE_PID_FILE}"
  fi
}

trap stop_bridge EXIT INT TERM

start_bridge
sleep 1

"${QWEN_PYTHON}" qwen_ros_node_edg_tts.py
