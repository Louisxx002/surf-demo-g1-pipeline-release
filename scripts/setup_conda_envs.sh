#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_ROOT}"

QWEN_ENV="${QWEN_ENV:-qwen}"
VOICE_ENV="${VOICE_ENV:-voice}"
QWEN_PYTHON_VERSION="${QWEN_PYTHON_VERSION:-3.12}"
VOICE_PYTHON_VERSION="${VOICE_PYTHON_VERSION:-3.11}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required. Install Miniconda/Anaconda first, then rerun this script." >&2
  exit 1
fi

eval "$(conda shell.bash hook)"

ensure_env() {
  local name="$1"
  local pyver="$2"
  if conda env list | awk '{print $1}' | grep -Fxq "${name}"; then
    echo "Conda env already exists: ${name}"
  else
    conda create -n "${name}" "python=${pyver}" -y
  fi
}

ensure_env "${QWEN_ENV}" "${QWEN_PYTHON_VERSION}"
conda activate "${QWEN_ENV}"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-qwen.txt
conda deactivate

ensure_env "${VOICE_ENV}" "${VOICE_PYTHON_VERSION}"
conda activate "${VOICE_ENV}"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-voice.txt
conda deactivate

cat <<EOF
Conda environments are ready.

Add these paths to config/local.env:
QWEN_PYTHON="\${HOME}/miniconda3/envs/${QWEN_ENV}/bin/python"
VOICE_PYTHON="\${HOME}/miniconda3/envs/${VOICE_ENV}/bin/python"
EOF
