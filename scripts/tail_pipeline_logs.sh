#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: tail_pipeline_logs.sh [all|core|voice|rag|llm|audio]

Groups:
  all    all integrated pipeline services
  core   SURF voice, RAG, LLM node, LLM server, audio player
  voice  SURF voice runtime and UDP ROS bridge
  rag    Ollama and XJTLU RAG server
  llm   LLM server and LLM ROS context node
  audio  Unitree audio player
EOF
}

GROUP="${1:-all}"

case "${GROUP}" in
  all)
    UNITS=(
      surf-voice-runtime
      surf-ros-bridge
      surf-llm-ollama
      surf-llm-rag
      surf-llm-server
      surf-llm-node
      surf-llm-audio-player
    )
    ;;
  core)
    UNITS=(
      surf-voice-runtime
      surf-llm-rag
      surf-llm-server
      surf-llm-node
      surf-llm-audio-player
    )
    ;;
  voice)
    UNITS=(surf-voice-runtime surf-ros-bridge)
    ;;
  rag)
    UNITS=(surf-llm-ollama surf-llm-rag)
    ;;
  llm|qwen)
    UNITS=(surf-llm-server surf-llm-node)
    ;;
  audio)
    UNITS=(surf-llm-audio-player)
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
