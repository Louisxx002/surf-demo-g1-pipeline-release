#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_ROOT}"

set -a
source "${WORKSPACE_ROOT}/config/default.env"
source "${SURF_ROOT}/config/default.env"
set +a

test -d "${SURF_ROOT}"
test -d "${LLM_ROOT}"
test -d "${LLM_ROOT}/third_party/unitree_sdk2_python"
test -f "${SURF_ROOT}/config/default.env"
test -f "${WORKSPACE_ROOT}/config/default.env"
test -f "${WORKSPACE_ROOT}/project_config.py"
test -f "${WORKSPACE_ROOT}/surf_voice_runtime.py"
test -f "${WORKSPACE_ROOT}/surf_ros_bridge.py"
test -f "${WORKSPACE_ROOT}/llm_server.py"
test -f "${WORKSPACE_ROOT}/llm_surf_context_node.py"
test -f "${WORKSPACE_ROOT}/unitree_audio_player.py"
test -f "${WORKSPACE_ROOT}/pipeline_log/pipeline_logger.py"
test -f "${WORKSPACE_ROOT}/wav.py"
test -f "${WORKSPACE_ROOT}/xjtlu-rag-system/app.py"
test -f "${WORKSPACE_ROOT}/xjtlu-rag-system/rag_index.db"
test -f "${WORKSPACE_ROOT}/xjtlu-rag-system/xjtlu_knowledge.db"
test -x "${OLLAMA_BIN}"

bash -n "${WORKSPACE_ROOT}/scripts/run_pipeline.sh"
bash -n "${WORKSPACE_ROOT}/scripts/stop_pipeline.sh"
bash -n "${WORKSPACE_ROOT}/scripts/monitor_audio_msg.sh"
bash -n "${WORKSPACE_ROOT}/scripts/run_llm_server.sh"
bash -n "${WORKSPACE_ROOT}/scripts/run_ollama_server.sh"
bash -n "${WORKSPACE_ROOT}/scripts/run_rag_server.sh"
bash -n "${WORKSPACE_ROOT}/scripts/run_surf_context_node.sh"
bash -n "${WORKSPACE_ROOT}/scripts/tail_pipeline_logs.sh"
bash -n "${WORKSPACE_ROOT}/scripts/run_audio_player.sh"
bash -n "${WORKSPACE_ROOT}/scripts/run_surf_voice_runtime.sh"
bash -n "${WORKSPACE_ROOT}/scripts/run_surf_ros_bridge.sh"
"${LLM_PYTHON}" - <<'PY'
import ast
from pathlib import Path

for path in (
    Path("project_config.py"),
    Path("llm_server.py"),
    Path("llm_surf_context_node.py"),
    Path("unitree_audio_player.py"),
    Path("pipeline_log/pipeline_logger.py"),
    Path("wav.py"),
    Path("surf_ros_bridge.py"),
    Path("xjtlu-rag-system/app.py"),
    Path("xjtlu-rag-system/chat_engine.py"),
    Path("xjtlu-rag-system/rag_config.py"),
    Path("xjtlu-rag-system/ollama_client.py"),
    Path("xjtlu-rag-system/vector_store.py"),
    Path("xjtlu-rag-system/memory_store.py"),
):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print(f"syntax ok: {path}")
PY

"${VOICE_PYTHON}" - <<'PY'
import ast
from pathlib import Path

for path in (Path("surf_voice_runtime.py"),):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print(f"syntax ok: {path}")
PY

if [[ "${LLM_AUTOSTART_ASR_BRIDGE}" != "0" ]]; then
  echo "LLM_AUTOSTART_ASR_BRIDGE must be 0 for this integrated workspace." >&2
  exit 1
fi

echo "SURF -> LLM workspace check passed."
