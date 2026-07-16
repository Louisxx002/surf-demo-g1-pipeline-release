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
export VOICE_VAD_SILENCE_FRAMES="${VOICE_VAD_SILENCE_FRAMES:-40}"
export VOICE_ASR_MAX_RECORDING_SEC="${VOICE_ASR_MAX_RECORDING_SEC:-20.0}"
export VOICE_ASR_PREROLL_FRAMES="${VOICE_ASR_PREROLL_FRAMES:-15}"
export VOICE_FOLLOWUP_CONTROL_POLL_SEC="${VOICE_FOLLOWUP_CONTROL_POLL_SEC:-0.02}"
export PYTHONPATH="${SURF_ROOT}:${WORKSPACE_ROOT}:${PYTHONPATH:-}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export SURF_BRIDGE_HOST="${SURF_BRIDGE_HOST:-127.0.0.1}"
export SURF_BRIDGE_PORT="${SURF_BRIDGE_PORT:-18765}"

printf '[voice-runtime-config] source=%s vad_holdoff_sec=%s vad_silence_frames=%s max_recording_sec=%s preroll_frames=%s followup_control_poll_sec=%s vad_aggressiveness=%s\n' \
  "${VOICE_AUDIO_SOURCE}" "${VOICE_VAD_HOLDOFF_SEC}" "${VOICE_VAD_SILENCE_FRAMES}" \
  "${VOICE_ASR_MAX_RECORDING_SEC}" "${VOICE_ASR_PREROLL_FRAMES}" "${VOICE_FOLLOWUP_CONTROL_POLL_SEC}" "${VOICE_VAD_AGGRESSIVENESS:-2}"

exec "${VOICE_PYTHON}" surf_voice_runtime.py
