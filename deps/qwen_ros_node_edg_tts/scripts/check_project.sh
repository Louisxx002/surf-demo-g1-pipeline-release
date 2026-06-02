#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

set -a
source "${PROJECT_ROOT}/config/default.env"
set +a
export QWEN_RUNTIME_DIR="${PROJECT_ROOT}/runtime"
export PYTHONDONTWRITEBYTECODE=1

"${QWEN_PYTHON}" - <<'PY'
import ast
from pathlib import Path

for name in (
    "project_config.py",
    "qwen_ros_node_edg_tts.py",
    "qwen_server.py",
    "unitree_audio_player.py",
    "asr_dds_to_ros_bridge.py",
    "wav.py",
):
    path = Path(name)
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print(f"syntax ok: {path}")
PY

"${QWEN_PYTHON}" - <<'PY'
from pathlib import Path
from project_config import CONFIG
print("project_root:", CONFIG.project_root)
print("runtime_dir:", CONFIG.runtime_dir)
print("audio_topic:", CONFIG.ros_audio_topic)
print("server_url:", CONFIG.qwen_server_url)
print("model_path_exists:", Path(CONFIG.model_path).exists(), CONFIG.model_path)
print("wake_words:", ", ".join(CONFIG.wake_words))
PY
