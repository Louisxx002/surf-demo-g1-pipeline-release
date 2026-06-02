#!/usr/bin/env bash
# Static project health check — does NOT start models or connect to the robot.
# Usage: ./scripts/check_project.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

PASS=0
FAIL=0

ok()   { echo "  [OK]   $*"; PASS=$((PASS+1)); }
fail() { echo "  [FAIL] $*"; FAIL=$((FAIL+1)); }

echo "=== SURF2026 VoiceModule project check ==="
echo ""

# ── 1. Config ─────────────────────────────────────────────────────────────────
echo "1. Config"
if [[ -f "${PROJECT_ROOT}/config/default.env" ]]; then
  ok "config/default.env exists"
else
  fail "config/default.env missing"
fi

set -a
source "${PROJECT_ROOT}/config/default.env" 2>/dev/null || true
set +a

if [[ -n "${VOICE_PYTHON:-}" ]]; then
  ok "VOICE_PYTHON = ${VOICE_PYTHON}"
else
  fail "VOICE_PYTHON not set in config/default.env"
fi

# ── 2. Python interpreter ─────────────────────────────────────────────────────
echo ""
echo "2. Python interpreter"
if [[ -x "${VOICE_PYTHON:-}" ]]; then
  ok "${VOICE_PYTHON} is executable"
else
  fail "${VOICE_PYTHON:-VOICE_PYTHON not set} not found or not executable"
fi

# ── 3. Python syntax ──────────────────────────────────────────────────────────
echo ""
echo "3. Python syntax"
syntax_ok=1
for f in config/voice_config.py audio/audio_bus.py audio/mic_capture.py \
          audio/robot_mic_capture.py vad/vad_engine.py \
          wake_word/chinese_wake_word_detector.py \
          wake_word/wakeup_dispatcher.py \
          asr/asr_engine.py voice_id/voiceprint_recognizer.py \
          voice_id/speaker_database.py ros_nodes/voice_pipeline_node.py; do
  if "${VOICE_PYTHON:-python3}" -m py_compile "${PROJECT_ROOT}/${f}" 2>/dev/null; then
    ok "${f}"
  else
    fail "${f} syntax error"
    syntax_ok=0
  fi
done

# ── 4. KWS model files ────────────────────────────────────────────────────────
echo ""
echo "4. KWS model files"
KWS_DIR="${VOICE_KWS_MODEL_DIR:-${PROJECT_ROOT}/models/kws}"
for pat in "encoder-*.int8.onnx" "decoder-*.int8.onnx" "joiner-*.int8.onnx" "tokens.txt" "keywords.txt"; do
  found=$(ls "${KWS_DIR}"/${pat} 2>/dev/null | head -1)
  if [[ -n "${found}" ]]; then
    ok "${pat} → $(basename "${found}")"
  else
    fail "${pat} not found in ${KWS_DIR}"
  fi
done

# ── 5. ASR model cache ────────────────────────────────────────────────────────
echo ""
echo "5. ASR model cache"
ASR_MODEL="${VOICE_ASR_MODEL:-}"
if [[ -n "${ASR_MODEL}" ]]; then
  if [[ -d "${ASR_MODEL}" ]]; then
    ok "VOICE_ASR_MODEL dir exists: ${ASR_MODEL}"
  else
    ok "VOICE_ASR_MODEL configured as model id: ${ASR_MODEL}"
  fi
else
  fail "VOICE_ASR_MODEL not set"
fi

# ── 6. Network config ─────────────────────────────────────────────────────────
echo ""
echo "6. Network config"
ok "UNITREE_DOMAIN_ID = ${UNITREE_DOMAIN_ID:-0}"
ok "UNITREE_NETWORK_INTERFACE = ${UNITREE_NETWORK_INTERFACE:-enp8s0}"
ok "VOICE_AUDIO_SOURCE = ${VOICE_AUDIO_SOURCE:-local}"
if [[ "${VOICE_AUDIO_SOURCE:-local}" == "robot" ]]; then
  ok "VOICE_ROBOT_MIC_GROUP = ${VOICE_ROBOT_MIC_GROUP:-239.168.123.161}"
  ok "VOICE_ROBOT_MIC_IF = ${VOICE_ROBOT_MIC_IF:-192.168.123.225}"
fi

# ── 7. ROS2 topics ────────────────────────────────────────────────────────────
echo ""
echo "7. ROS2 topics"
ok "VOICE_ROS_AUDIO_TOPIC = ${VOICE_ROS_AUDIO_TOPIC:-/audio_msg}"
ok "VOICE_ROS_WAKE_TOPIC  = ${VOICE_ROS_WAKE_TOPIC:-/wake_word_event}"
ok "VOICE_ROS_VAD_TOPIC   = ${VOICE_ROS_VAD_TOPIC:-/vad_state}"
ok "VOICE_ROS_SPEAKER_TOPIC = ${VOICE_ROS_SPEAKER_TOPIC:-/speaker_id}"

# ── 8. Core package imports ───────────────────────────────────────────────────
echo ""
echo "8. Core package imports"
PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}" "${VOICE_PYTHON:-python3}" - <<'PYEOF' 2>&1 | while IFS= read -r line; do
import sys
checks = [
    ("webrtcvad",   "import webrtcvad"),
    ("sherpa_onnx", "import sherpa_onnx"),
    ("funasr",      "from funasr import AutoModel"),
    ("pyannote",    "from pyannote.audio import Model"),
    ("numpy",       "import numpy"),
    ("sounddevice", "import sounddevice"),
]
for name, stmt in checks:
    try:
        exec(stmt)
        print(f"OK {name}")
    except Exception as e:
        print(f"FAIL {name}: {e}")
PYEOF
  if [[ "${line}" == OK* ]]; then
    ok "${line#OK }"
  else
    fail "${line#FAIL }"
  fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Result: ${PASS} passed, ${FAIL} failed ==="
if [[ ${FAIL} -eq 0 ]]; then
  echo "SURF2026 VOICE MODULE CHECK PASSED"
  exit 0
else
  echo "Fix the failures above before running the node."
  exit 1
fi
