#!/usr/bin/env bash
set -euo pipefail

systemctl --user stop \
  qwen-asr-bridge.service \
  qwen-server.service \
  qwen-ros-node.service \
  qwen-audio-player.service >/dev/null 2>&1 || true

pkill -f 'asr_dds_to_ros_bridge.py --network' >/dev/null 2>&1 || true

echo "Stopped full pipeline services."
