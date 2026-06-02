#!/usr/bin/env bash
set -euo pipefail

MODE="listen"
WAKE_WORDS=""

usage() {
  cat <<'EOF'
Usage: run_full_pipeline.sh [--mode listen|wake] [--wake-word WORD]

Examples:
  ./scripts/run_full_pipeline.sh
  ./scripts/run_full_pipeline.sh --mode wake --wake-word "小g"
  ./scripts/run_full_pipeline.sh --mode listen
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --mode=*)
      MODE="${1#*=}"
      shift
      ;;
    --wake-word)
      WAKE_WORDS="${2:-}"
      shift 2
      ;;
    --wake-word=*)
      WAKE_WORDS="${1#*=}"
      shift
      ;;
    --wake-words)
      WAKE_WORDS="${2:-}"
      shift 2
      ;;
    --wake-words=*)
      WAKE_WORDS="${1#*=}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "${MODE}" != "listen" && "${MODE}" != "wake" ]]; then
  echo "Invalid --mode value: ${MODE}" >&2
  usage >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

export QWEN_ALWAYS_LISTEN="1"
if [[ "${MODE}" == "wake" ]]; then
  export QWEN_ALWAYS_LISTEN="0"
fi
if [[ -n "${WAKE_WORDS}" ]]; then
  export QWEN_WAKE_WORDS="${WAKE_WORDS}"
fi

set -a
source "${PROJECT_ROOT}/config/default.env"
set +a

export QWEN_RUNTIME_DIR="${PROJECT_ROOT}/runtime"
export ROS_LOG_DIR="${PROJECT_ROOT}/runtime/ros_logs"
export PYTHONPATH="${PROJECT_ROOT}/third_party/unitree_sdk2_python:${PYTHONPATH:-}"
export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"
mkdir -p "${QWEN_RUNTIME_DIR}" "${ROS_LOG_DIR}"

SYSTEMD_ENV=(
  --setenv=QWEN_ALWAYS_LISTEN="${QWEN_ALWAYS_LISTEN}"
  --setenv=QWEN_AUTOSTART_ASR_BRIDGE=1
)
if [[ -n "${WAKE_WORDS}" ]]; then
  SYSTEMD_ENV+=(--setenv=QWEN_WAKE_WORDS="${WAKE_WORDS}")
fi

systemctl --user stop \
  qwen-asr-bridge.service \
  qwen-server.service \
  qwen-ros-node.service \
  qwen-audio-player.service >/dev/null 2>&1 || true

systemd-run --user --unit=qwen-server --same-dir --collect "${SYSTEMD_ENV[@]}" \
  /home/louisxx/qwen_ros_node_edg_tts/scripts/run_server.sh >/dev/null

echo "Waiting for Qwen server to become healthy..."
for _ in $(seq 1 120); do
  if env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
      NO_PROXY=127.0.0.1,localhost \
      curl -fsS --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

systemd-run --user --unit=qwen-ros-node --same-dir --collect "${SYSTEMD_ENV[@]}" \
  /home/louisxx/qwen_ros_node_edg_tts/scripts/run_ros_node.sh >/dev/null

systemd-run --user --unit=qwen-audio-player --same-dir --collect "${SYSTEMD_ENV[@]}" \
  /home/louisxx/qwen_ros_node_edg_tts/scripts/run_audio_player.sh >/dev/null

echo "Full pipeline started."
echo "Mode: ${MODE}"
if [[ -n "${WAKE_WORDS}" ]]; then
  echo "Wake words: ${WAKE_WORDS}"
fi
echo "Qwen server: qwen-server.service"
echo "ROS node: qwen-ros-node.service"
echo "Player: qwen-audio-player.service"
