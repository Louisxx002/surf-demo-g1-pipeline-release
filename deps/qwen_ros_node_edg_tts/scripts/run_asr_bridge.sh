#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

set -a
source "${PROJECT_ROOT}/config/default.env"
set +a

set +u
source /opt/ros/jazzy/setup.bash
set -u

export PYTHONPATH="${PROJECT_ROOT}/third_party/unitree_sdk2_python:${PYTHONPATH:-}"

echo "Starting safe ASR bridge: Unitree DDS rt/audio_msg -> ROS2 ${QWEN_AUDIO_TOPIC}"
echo "Network interface: ${UNITREE_NETWORK_INTERFACE}, domain: ${UNITREE_DOMAIN_ID}"
"${QWEN_PYTHON}" asr_dds_to_ros_bridge.py \
  --network "${UNITREE_NETWORK_INTERFACE}" \
  --domain-id "${UNITREE_DOMAIN_ID}" \
  --ros-topic "${QWEN_AUDIO_TOPIC}"
