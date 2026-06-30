# Reproducibility Guide

This repository is source-ready for GitHub, but it is not a fully bundled
runtime image. Large local artifacts, generated files, and secrets are excluded
from Git on purpose.

## What Is Included

- Integrated SURF/LLM workspace source files.
- SURF voice module source under `deps/SURF2026_VoiceModule-main/`.
- Unitree SDK source/library headers under `deps/unitree_g1_action_classifier_package/unitree_sdk2/`.
- Vendored Unitree Python SDK under `deps/qwen_ros_node_edg_tts/third_party/unitree_sdk2_python/`.
- XJTLU RAG source and small SQLite knowledge/index databases:
  - `xjtlu-rag-system/xjtlu_knowledge.db`
  - `xjtlu-rag-system/rag_index.db`
- Safe default configuration in `config/default.env`.
- Reproducible local configuration template in `config/local.env.example`.

## What Is Not Included

These are intentionally ignored:

- `config/local.env`: local API keys and machine-specific overrides.
- `deps/ollama/`: local Ollama binary bundle.
- `deps/ollama-home/`: local Ollama model cache.
- `deps/Qwen3.5-0.8B/`: local Qwen model weights, currently unused by the default RAG backend.
- `deps/unitree_g1_action_classifier_package/.venv/`: local action classifier virtual environment.
- `deps/unitree_g1_action_classifier_package/unitree_sdk2/build/`: generated CMake build outputs, including `g1_arm_action_example`.
- `*.onnx`: downloaded wake-word model binaries.
- `runtime/`, `logs/`, `logs.zip`, TTS wav/mp3 outputs, and chat memory.

## Required Runtime Environment

- Ubuntu/WSL2 environment similar to the original deployment.
- ROS2 Jazzy installed at `/opt/ros/jazzy`.
- Python/conda environment for the main pipeline, installed from
  `requirements-llm.txt`, default path:
  - `$HOME/miniconda3/envs/llm/bin/python`
- Python/conda environment for the voice pipeline, installed from
  `requirements-voice.txt`, default path:
  - `$HOME/miniconda3/envs/voice/bin/python`
- DeepSeek-compatible OpenAI API key.
- Ollama with `nomic-embed-text` available locally.
- Unitree G1 network access through the configured interface, default:
  - `enp8s0`
- CycloneDDS through the bundled Unitree SDK:
  - Python SDK dependency: `cyclonedds==0.10.2`
  - C++ SDK libraries: bundled `ddsc` and `ddscxx`

## Local Configuration

Create `config/local.env` after cloning. This file is git-ignored:

```bash
cp config/local.env.example config/local.env
```

Then edit `config/local.env` and fill in values for the target machine,
especially:

- `OPENAI_API_KEY`
- `LLM_PYTHON`
- `VOICE_PYTHON`
- `UNITREE_NETWORK_INTERFACE`
- `VOICE_ROBOT_MIC_IF` and `VOICE_ROBOT_MIC_PORT`

If using restored local assets from another machine, place them under `deps/`
or update the matching paths in `config/local.env`.

## Restore Missing Runtime Assets

Install or restore Ollama, then pull the embedding model:

```bash
ollama pull nomic-embed-text
```

Build the Unitree action runner if it is not restored:

```bash
cd deps/unitree_g1_action_classifier_package/unitree_sdk2
mkdir -p build
cd build
cmake ..
make -j
```

The pipeline expects this binary unless overridden:

```text
deps/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example
```

Install the Python Unitree SDK so CycloneDDS is available in the main pipeline
environment. This is already included by `requirements-llm.txt`; run this only
if you installed dependencies manually:

```bash
${LLM_PYTHON:-$HOME/miniconda3/envs/llm/bin/python} -m pip install -e deps/qwen_ros_node_edg_tts/third_party/unitree_sdk2_python
```

DDS is bound to `UNITREE_NETWORK_INTERFACE`. If your robot or DDS peer is not
discoverable by multicast, set `CYCLONEDDS_URI` in `config/local.env` with the
correct peer IP for that machine.

Restore/download wake-word ONNX model files under:

```text
deps/SURF2026_VoiceModule-main/models/kws/
```

The repo includes `keywords.txt` and `tokens.txt`, but not the ONNX binaries.

## Default Pipeline Behavior

The default source configuration is:

```text
LLM_REPLY_BACKEND=rag
CHAT_PROVIDER=openai
CHAT_MODEL=deepseek-v4-pro
EMBED_PROVIDER=ollama
EMBED_MODEL=nomic-embed-text
LLM_ACTION_BACKEND=deepseek
```

Current flow:

```text
G1 mic UDP audio
-> SURF wake/VAD/ASR/speaker
-> ROS2 /audio_msg
-> XJTLU RAG + Ollama embedding
-> DeepSeek reply + action JSON
-> Edge TTS
-> Unitree DDS audio playback
-> Unitree G1 action runner
```

## Validation

Run syntax/config checks:

```bash
./scripts/check_pipeline.sh
```

Start services:

```bash
./scripts/run_pipeline.sh --mode wake
```

Follow logs:

```bash
./scripts/tail_pipeline_logs.sh all
```

Stop services:

```bash
./scripts/stop_pipeline.sh
```

## Known Non-Reproducible Parts Without Local Assets

The repository alone is enough to inspect and develop the code, but a fresh
machine cannot run the full robot demo until the excluded model/runtime assets,
API key, ROS2 environment, and Unitree network/build outputs are restored.

## Release Bundle

For a handoff that includes local model/runtime assets, build a release bundle:

```bash
./scripts/build_release_bundle.sh --output ./release-output --name surf_llm_bundle --tar
```

The bundle excludes local secrets and generated runtime output. The receiver
must edit `bundle.env` or export environment variables for `VOICE_PYTHON`,
`LLM_PYTHON`, and `OPENAI_API_KEY` before running `./run.sh`.
