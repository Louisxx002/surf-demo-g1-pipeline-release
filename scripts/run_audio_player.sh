#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_ROOT}"

set -a
source "${WORKSPACE_ROOT}/config/default.env"
set +a

export QWEN_RUNTIME_DIR="${WORKSPACE_ROOT}/runtime"
export PYTHONPATH="${WORKSPACE_ROOT}:${QWEN_ROOT}/third_party/unitree_sdk2_python:${PYTHONPATH:-}"
mkdir -p "${QWEN_RUNTIME_DIR}"

exec "${QWEN_PYTHON}" unitree_audio_player.py
