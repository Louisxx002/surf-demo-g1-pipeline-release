#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ROBOT_HOST="${ROBOT_RELAY_HOST:-192.168.123.164}"
ROBOT_USER="${ROBOT_SSH_USER:-unitree}"
ROBOT_ROOT="${ROBOT_MIC_RUNTIME_ROOT:-/home/unitree/surf_robot_mic}"
SSH_KEY="${ROBOT_SSH_IDENTITY_FILE:-${HOME}/.ssh/surf_robot_ed25519}"
SSH_OPTIONS=(
  -i "${SSH_KEY}"
  -o BatchMode=yes
  -o ConnectTimeout=5
  -o StrictHostKeyChecking=accept-new
)
REMOTE="${ROBOT_USER}@${ROBOT_HOST}"

if [[ ! -f "${SSH_KEY}" ]]; then
  echo "SSH key not found: ${SSH_KEY}" >&2
  exit 1
fi

ssh "${SSH_OPTIONS[@]}" "${REMOTE}" \
  "mkdir -p '${ROBOT_ROOT}/beamforming' '${ROBOT_ROOT}/tools' '${ROBOT_ROOT}/filters' '${ROBOT_ROOT}/logs'"

scp "${SSH_OPTIONS[@]}" \
  "${PROJECT_ROOT}/beamforming/__init__.py" \
  "${PROJECT_ROOT}/beamforming/filter_io.py" \
  "${PROJECT_ROOT}/beamforming/fixed_mini_beamformer.py" \
  "${PROJECT_ROOT}/beamforming/mic_runtime.py" \
  "${PROJECT_ROOT}/beamforming/stream_adapter.py" \
  "${REMOTE}:${ROBOT_ROOT}/beamforming/"

scp "${SSH_OPTIONS[@]}" \
  "${PROJECT_ROOT}/deps/SURF2026_VoiceModule-main/tools/stream_usb_mic.py" \
  "${REMOTE}:${ROBOT_ROOT}/tools/stream_usb_mic.py"

scp "${SSH_OPTIONS[@]}" \
  "${PROJECT_ROOT}/research/beamforming/teacher_reference_20260630/DCF_Targ7_runtime.npz" \
  "${REMOTE}:${ROBOT_ROOT}/filters/DCF_Targ7_runtime.npz"

ssh "${SSH_OPTIONS[@]}" "${REMOTE}" \
  "PYTHONPATH='${ROBOT_ROOT}' /usr/bin/python3 '${ROBOT_ROOT}/tools/stream_usb_mic.py' --help >/dev/null"

echo "Robot microphone runtime deployed to ${REMOTE}:${ROBOT_ROOT}"
echo "Default processing mode: mean4 (8 input channels, source channels 0,1,2,3)"
