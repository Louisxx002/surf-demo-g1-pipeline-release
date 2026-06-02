#!/usr/bin/env bash
set -euo pipefail

systemctl --user stop \
  voice-pipeline.service \
  surf-voice-runtime.service \
  surf-ros-bridge.service \
  qwen-asr-bridge.service \
  qwen-server.service \
  qwen-ros-node.service \
  qwen-audio-player.service \
  surf-qwen-ollama.service \
  surf-qwen-rag.service \
  surf-qwen-server.service \
  surf-qwen-node.service \
  surf-qwen-audio-player.service >/dev/null 2>&1 || true

pkill -f 'asr_dds_to_ros_bridge.py --network' >/dev/null 2>&1 || true

echo "Stopped SURF -> Qwen integrated pipeline services."
