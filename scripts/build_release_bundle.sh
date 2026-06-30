#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: build_release_bundle.sh [--output DIR] [--name NAME] [--tar]

Build a relocatable release bundle containing:
  - surf_llm_workspace
  - SURF2026_VoiceModule-main
  - qwen_ros_node_edg_tts third_party Unitree SDK subtree
  - unitree_g1_action_classifier_package source and runner
  - local Qwen model directory
  - SURF ASR model directory
  - Hugging Face voiceprint cache

The bundle still needs working voice/LLM Python environments on the target
machine. Set VOICE_PYTHON and LLM_PYTHON before running the bundled launcher.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${WORKSPACE_ROOT}"

OUTPUT_DIR="${HOME}/surf_llm_release"
NAME="surf_llm_bundle"
MAKE_TAR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --output=*)
      OUTPUT_DIR="${1#*=}"
      shift
      ;;
    --name)
      NAME="${2:-}"
      shift 2
      ;;
    --name=*)
      NAME="${1#*=}"
      shift
      ;;
    --tar)
      MAKE_TAR=1
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

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required to build the bundle." >&2
  exit 1
fi

set -a
source "${WORKSPACE_ROOT}/config/default.env"
source "${SURF_ROOT}/config/default.env"
set +a

SURF_ROOT_REAL="$(readlink -f "${SURF_ROOT}")"
LLM_ROOT_REAL="$(readlink -f "${LLM_ROOT}")"
ACTION_ROOT_REAL="$(readlink -f "$(dirname "$(dirname "${LLM_ACTION_SCRIPT}")")")"
LLM_MODEL_REAL="$(readlink -f "${LLM_MODEL_PATH}")"
VOICE_ASR_MODEL_REAL="$(readlink -f "${VOICE_ASR_MODEL}")"
VOICEPRINT_REAL="${HOME}/.cache/huggingface/hub/models--pyannote--wespeaker-voxceleb-resnet34-LM"

TARGET_ROOT="${OUTPUT_DIR%/}/${NAME}"
rm -rf "${TARGET_ROOT}"
mkdir -p "${TARGET_ROOT}"/{deps,models,cache,workspace}

copy_tree() {
  local src="$1"
  local dst="$2"
  shift 2 || true
  if [[ ! -e "${src}" ]]; then
    echo "Missing source: ${src}" >&2
    exit 1
  fi
  mkdir -p "${dst}"
  rsync -a --delete "$@" "${src}/" "${dst}/"
}

copy_tree "${WORKSPACE_ROOT}" "${TARGET_ROOT}/workspace/surf_llm_workspace" \
  --exclude '.git' \
  --exclude '.agents' \
  --exclude '.codex' \
  --exclude '.env' \
  --exclude '*.local.env' \
  --exclude 'config/local.env' \
  --exclude 'deps' \
  --exclude 'runtime' \
  --exclude 'release-output' \
  --exclude 'surf_llm_bundle' \
  --exclude 'surf_llm_bundle.tar' \
  --exclude 'logs' \
  --exclude 'logs.zip' \
  --exclude '*.log' \
  --exclude '*.wav' \
  --exclude '*.mp3' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache'

copy_tree "${SURF_ROOT_REAL}" "${TARGET_ROOT}/deps/SURF2026_VoiceModule-main" \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'runtime'

mkdir -p "${TARGET_ROOT}/deps/qwen_ros_node_edg_tts/third_party"
copy_tree "${LLM_ROOT_REAL}/third_party/unitree_sdk2_python" \
  "${TARGET_ROOT}/deps/qwen_ros_node_edg_tts/third_party/unitree_sdk2_python"

copy_tree "${ACTION_ROOT_REAL}" "${TARGET_ROOT}/deps/unitree_g1_action_classifier_package" \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache'

mkdir -p "${TARGET_ROOT}/models/Qwen3.5-0.8B"
copy_tree "${LLM_MODEL_REAL}" "${TARGET_ROOT}/models/Qwen3.5-0.8B/model"

mkdir -p "${TARGET_ROOT}/cache/modelscope/hub/models/iic"
copy_tree "${VOICE_ASR_MODEL_REAL}" \
  "${TARGET_ROOT}/cache/modelscope/hub/models/iic/$(basename "${VOICE_ASR_MODEL_REAL}")"

if [[ -d "${VOICEPRINT_REAL}" ]]; then
  mkdir -p "${TARGET_ROOT}/cache/huggingface/hub"
  copy_tree "${VOICEPRINT_REAL}" "${TARGET_ROOT}/cache/huggingface/hub/$(basename "${VOICEPRINT_REAL}")"
fi

cat > "${TARGET_ROOT}/bundle.env.example" <<EOF
# Fill these in on the target machine before running ./run.sh
export VOICE_PYTHON="/path/to/voice/env/bin/python"
export LLM_PYTHON="/path/to/llm/env/bin/python"
export OPENAI_API_KEY="sk-your-deepseek-api-key"

# Optional overrides if the target machine needs custom network settings.
export UNITREE_NETWORK_INTERFACE="${UNITREE_NETWORK_INTERFACE:-enp8s0}"
export UNITREE_DOMAIN_ID="${UNITREE_DOMAIN_ID:-0}"
export DASHSCOPE_API_KEY=""
EOF

cat > "${TARGET_ROOT}/bundle.env" <<EOF
export SURF_LLM_BUNDLE_ROOT="${TARGET_ROOT}"
export SURF_ROOT="${TARGET_ROOT}/deps/SURF2026_VoiceModule-main"
export LLM_ROOT="${TARGET_ROOT}/deps/qwen_ros_node_edg_tts"
export LLM_MODEL_PATH="${TARGET_ROOT}/models/Qwen3.5-0.8B/model"
export VOICE_ASR_MODEL="${TARGET_ROOT}/cache/modelscope/hub/models/iic/$(basename "${VOICE_ASR_MODEL_REAL}")"
export VOICE_VOICEPRINT_MODEL="pyannote/wespeaker-voxceleb-resnet34-LM"
export VOICE_PYTHON="\${VOICE_PYTHON:-}"
export LLM_PYTHON="\${LLM_PYTHON:-}"
export MODELSCOPE_CACHE="${TARGET_ROOT}/cache/modelscope"
export HF_HOME="${TARGET_ROOT}/cache/huggingface"
export HF_HUB_CACHE="${TARGET_ROOT}/cache/huggingface/hub"
export LLM_ACTION_PYTHON="\${LLM_ACTION_PYTHON:-\${LLM_PYTHON:-\${VOICE_PYTHON:-python3}}}"
export LLM_ACTION_SCRIPT="${TARGET_ROOT}/deps/unitree_g1_action_classifier_package/arm_action_classifier/arm_action_classifier.py"
export LLM_ACTION_RUNNER="${TARGET_ROOT}/deps/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example"
export LLM_RUNTIME_DIR="${TARGET_ROOT}/workspace/surf_llm_workspace/runtime"
export OPENAI_API_KEY="\${OPENAI_API_KEY:-}"
export DASHSCOPE_API_KEY="\${DASHSCOPE_API_KEY:-}"
EOF

cat > "${TARGET_ROOT}/run.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROOT}/bundle.env"
if [[ -z "${VOICE_PYTHON:-}" || ! -x "${VOICE_PYTHON}" ]]; then
  echo "VOICE_PYTHON is not set to an executable path." >&2
  echo "Copy bundle.env.example to bundle.env and set VOICE_PYTHON." >&2
  exit 1
fi
if [[ -z "${LLM_PYTHON:-}" || ! -x "${LLM_PYTHON}" ]]; then
  echo "LLM_PYTHON is not set to an executable path." >&2
  echo "Copy bundle.env.example to bundle.env and set LLM_PYTHON." >&2
  exit 1
fi
cd "${ROOT}/workspace/surf_llm_workspace"
exec ./scripts/run_pipeline.sh "$@"
EOF
chmod +x "${TARGET_ROOT}/run.sh"

cat > "${TARGET_ROOT}/check.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROOT}/bundle.env"
test -d "${SURF_ROOT}"
test -d "${LLM_ROOT}"
test -d "${LLM_MODEL_PATH}"
test -d "${VOICE_ASR_MODEL}"
test -x "${LLM_ACTION_RUNNER}"
echo "Bundle layout looks complete."
EOF
chmod +x "${TARGET_ROOT}/check.sh"

cat > "${TARGET_ROOT}/README.md" <<'EOF'
# SURF LLM Release Bundle

This bundle is relocatable. The code and model directories are included; the
voice and LLM Python environments are still external.

Before running, edit `bundle.env` and set:

```bash
export VOICE_PYTHON=/path/to/voice/env/bin/python
export LLM_PYTHON=/path/to/llm/env/bin/python
```

Then run:

```bash
./run.sh
```

Optional verification:

```bash
./check.sh
```
EOF

if [[ "${MAKE_TAR}" == "1" ]]; then
  tarball="${TARGET_ROOT}.tar"
  tar -cf "${tarball}" -C "${OUTPUT_DIR}" "${NAME}"
  echo "Created bundle: ${TARGET_ROOT}"
  echo "Created tarball: ${tarball}"
else
  echo "Created bundle: ${TARGET_ROOT}"
fi
