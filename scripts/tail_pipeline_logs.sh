#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: tail_pipeline_logs.sh [all|core|voice|rag|qwen|audio]

Groups:
  all    all integrated pipeline services
  core   SURF voice, RAG, qwen node, qwen server, audio player
  voice  SURF voice runtime and UDP ROS bridge
  rag    Ollama and XJTLU RAG server
  qwen   qwen server and qwen ROS context node
  audio  Unitree audio player
EOF
}

GROUP="${1:-all}"

case "${GROUP}" in
  all)
    UNITS=(
      surf-voice-runtime
      surf-ros-bridge
      surf-qwen-ollama
      surf-qwen-rag
      surf-qwen-server
      surf-qwen-node
      surf-qwen-audio-player
    )
    ;;
  core)
    UNITS=(
      surf-voice-runtime
      surf-qwen-rag
      surf-qwen-server
      surf-qwen-node
      surf-qwen-audio-player
    )
    ;;
  voice)
    UNITS=(surf-voice-runtime surf-ros-bridge)
    ;;
  rag)
    UNITS=(surf-qwen-ollama surf-qwen-rag)
    ;;
  qwen)
    UNITS=(surf-qwen-server surf-qwen-node)
    ;;
  audio)
    UNITS=(surf-qwen-audio-player)
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown log group: ${GROUP}" >&2
    usage >&2
    exit 1
    ;;
esac

ARGS=(--user -f -n 80 --no-pager)
for unit in "${UNITS[@]}"; do
  ARGS+=(-u "${unit}")
done

echo "Following logs for: ${UNITS[*]}"
exec journalctl "${ARGS[@]}"
