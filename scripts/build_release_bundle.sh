#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: build_release_bundle.sh [--output DIR] [--name NAME] [--tar]

Build a relocatable release bundle containing:
  - surf_qwen_workspace
  - SURF2026_VoiceModule-main
  - qwen_ros_node_edg_tts third_party Unitree SDK subtree
  - unitree_g1_action_classifier_package source and runner
  - local Qwen model directory
  - SURF ASR model directory
  - Hugging Face voiceprint cache

The bundle still needs working voice/qwen Python environments on the target
machine. Set VOICE_PYTHON and QWEN_PYTHON before running the bundled launcher.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${WORKSPACE_ROOT}"

OUTPUT_DIR="${HOME}/surf_qwen_release"
NAME="surf_qwen_bundle"
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
QWEN_ROOT_REAL="$(readlink -f "${QWEN_ROOT}")"
ACTION_ROOT_REAL="$(readlink -f "$(dirname "$(dirname "${QWEN_ACTION_SCRIPT}")")")"
QWEN_MODEL_REAL="$(readlink -f "${QWEN_MODEL_PATH}")"
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

copy_tree "${WORKSPACE_ROOT}" "${TARGET_ROOT}/workspace/surf_qwen_workspace" \
  --exclude '.git' \
  --exclude 'runtime' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache'

copy_tree "${SURF_ROOT_REAL}" "${TARGET_ROOT}/deps/SURF2026_VoiceModule-main" \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'runtime'

mkdir -p "${TARGET_ROOT}/deps/qwen_ros_node_edg_tts/third_party"
copy_tree "${QWEN_ROOT_REAL}/third_party/unitree_sdk2_python" \
  "${TARGET_ROOT}/deps/qwen_ros_node_edg_tts/third_party/unitree_sdk2_python"

copy_tree "${ACTION_ROOT_REAL}" "${TARGET_ROOT}/deps/unitree_g1_action_classifier_package" \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache'

mkdir -p "${TARGET_ROOT}/models/Qwen3.5-0.8B"
copy_tree "${QWEN_MODEL_REAL}" "${TARGET_ROOT}/models/Qwen3.5-0.8B/model"

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
export QWEN_PYTHON="/path/to/qwen/env/bin/python"

# Optional overrides if the target machine needs custom network settings.
export UNITREE_NETWORK_INTERFACE="${UNITREE_NETWORK_INTERFACE:-enp8s0}"
export UNITREE_DOMAIN_ID="${UNITREE_DOMAIN_ID:-0}"
EOF

cat > "${TARGET_ROOT}/bundle.env" <<EOF
export SURF_QWEN_BUNDLE_ROOT="${TARGET_ROOT}"
export SURF_ROOT="${TARGET_ROOT}/deps/SURF2026_VoiceModule-main"
export QWEN_ROOT="${TARGET_ROOT}/deps/qwen_ros_node_edg_tts"
export QWEN_MODEL_PATH="${TARGET_ROOT}/models/Qwen3.5-0.8B/model"
export VOICE_ASR_MODEL="${TARGET_ROOT}/cache/modelscope/hub/models/iic/$(basename "${VOICE_ASR_MODEL_REAL}")"
export VOICE_VOICEPRINT_MODEL="pyannote/wespeaker-voxceleb-resnet34-LM"
export VOICE_PYTHON="\${VOICE_PYTHON:-}"
export QWEN_PYTHON="\${QWEN_PYTHON:-}"
export MODELSCOPE_CACHE="${TARGET_ROOT}/cache/modelscope"
export HF_HOME="${TARGET_ROOT}/cache/huggingface"
export HF_HUB_CACHE="${TARGET_ROOT}/cache/huggingface/hub"
export QWEN_ACTION_PYTHON="\${QWEN_ACTION_PYTHON:-\${QWEN_PYTHON:-\${VOICE_PYTHON:-python3}}}"
export QWEN_ACTION_SCRIPT="${TARGET_ROOT}/deps/unitree_g1_action_classifier_package/arm_action_classifier/arm_action_classifier.py"
export QWEN_ACTION_RUNNER="${TARGET_ROOT}/deps/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example"
export QWEN_RUNTIME_DIR="${TARGET_ROOT}/workspace/surf_qwen_workspace/runtime"
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
if [[ -z "${QWEN_PYTHON:-}" || ! -x "${QWEN_PYTHON}" ]]; then
  echo "QWEN_PYTHON is not set to an executable path." >&2
  echo "Copy bundle.env.example to bundle.env and set QWEN_PYTHON." >&2
  exit 1
fi
cd "${ROOT}/workspace/surf_qwen_workspace"
exec ./scripts/run_pipeline.sh "$@"
EOF
chmod +x "${TARGET_ROOT}/run.sh"

cat > "${TARGET_ROOT}/check.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${ROOT}/bundle.env"
test -d "${SURF_ROOT}"
test -d "${QWEN_ROOT}"
test -d "${QWEN_MODEL_PATH}"
test -d "${VOICE_ASR_MODEL}"
test -x "${QWEN_ACTION_RUNNER}"
echo "Bundle layout looks complete."
EOF
chmod +x "${TARGET_ROOT}/check.sh"

cat > "${TARGET_ROOT}/README.md" <<'EOF'
# SURF Qwen Release Bundle

This bundle is relocatable. The code and model directories are included; the
voice and Qwen Python environments are still external.

Before running, edit `bundle.env` and set:

```bash
export VOICE_PYTHON=/path/to/voice/env/bin/python
export QWEN_PYTHON=/path/to/qwen/env/bin/python
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
