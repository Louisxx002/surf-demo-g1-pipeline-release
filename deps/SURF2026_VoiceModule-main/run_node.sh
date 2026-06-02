#!/usr/bin/env bash
# Launch voice_pipeline_node.  Sources config/default.env for all settings.
# Usage: bash run_node.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

set -a
source "${SCRIPT_DIR}/config/default.env"
set +a

export HF_HUB_OFFLINE=1
export ROS_DOMAIN_ID="${UNITREE_DOMAIN_ID}"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><AllowMulticast>false</AllowMulticast></General><Discovery><Peers><Peer address=\"192.168.123.164\"/></Peers></Discovery></Domain></CycloneDDS>"

set +u
source /opt/ros/jazzy/setup.bash
set -u

exec "${VOICE_PYTHON}" ros_nodes/voice_pipeline_node.py
