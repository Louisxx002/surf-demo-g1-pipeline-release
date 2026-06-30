#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_ROOT}"

set -a
source "${WORKSPACE_ROOT}/config/default.env"
source "${SURF_ROOT}/config/default.env"
set +a

export VOICE_AUDIO_SOURCE="${VOICE_AUDIO_SOURCE:-robot}"
export VOICE_ASR_WINDOW_SEC="${SURF_LLM_ASR_WINDOW_SEC:-${VOICE_ASR_WINDOW_SEC:-8.0}}"
export VOICE_VAD_HOLDOFF_SEC="${SURF_LLM_VAD_HOLDOFF_SEC:-${VOICE_VAD_HOLDOFF_SEC:-4.0}}"
export PYTHONPATH="${SURF_ROOT}:${WORKSPACE_ROOT}:${PYTHONPATH:-}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export SURF_BRIDGE_HOST="${SURF_BRIDGE_HOST:-127.0.0.1}"
export SURF_BRIDGE_PORT="${SURF_BRIDGE_PORT:-18765}"

exec "${VOICE_PYTHON}" surf_voice_runtime.py
