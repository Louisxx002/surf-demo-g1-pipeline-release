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
  surf-llm-ollama.service \
  surf-llm-rag.service \
  surf-llm-server.service \
  surf-llm-node.service \
  surf-llm-audio-player.service >/dev/null 2>&1 || true

pkill -f 'asr_dds_to_ros_bridge.py --network' >/dev/null 2>&1 || true

echo "Stopped SURF -> LLM integrated pipeline services."
