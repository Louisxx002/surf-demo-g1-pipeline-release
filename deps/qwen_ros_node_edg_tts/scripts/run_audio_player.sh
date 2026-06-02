#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

set -a
source "${PROJECT_ROOT}/config/default.env"
set +a
export QWEN_RUNTIME_DIR="${PROJECT_ROOT}/runtime"
export PYTHONPATH="${PROJECT_ROOT}/third_party/unitree_sdk2_python:${PYTHONPATH:-}"

"${QWEN_PYTHON}" unitree_audio_player.py
