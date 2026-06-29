# Environment Setup

This project is intended to run in a Linux/WSL2 + ROS2 Jazzy environment with
access to a Unitree G1 robot network.

The repository keeps source code and small databases in Git. It does not commit
large binaries, local conda environments, model caches, generated builds, or API
keys.

## System Packages

Install the baseline tools:

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  cmake \
  curl \
  ffmpeg \
  git \
  portaudio19-dev \
  python3-dev \
  python3-pip
```

Install ROS2 Jazzy separately and make sure this file exists:

```text
/opt/ros/jazzy/setup.bash
```

The launch scripts source it before starting ROS nodes.

## Conda Environments

The default config expects a main Python environment named `qwen`:

```bash
conda create -n qwen python=3.12 -y
conda activate qwen
python -m pip install --upgrade pip
python -m pip install -r requirements-qwen.txt
```

The SURF voice module may use a separate environment:

```bash
conda create -n voice python=3.11 -y
conda activate voice
python -m pip install --upgrade pip
python -m pip install -r requirements-voice.txt
```

The old component-level requirements files are kept as compatibility shims:

```text
xjtlu-rag-system/requirements.txt
deps/qwen_ros_node_edg_tts/requirements.txt
deps/unitree_g1_action_classifier_package/requirements.txt
deps/SURF2026_VoiceModule-main/requirements.txt
```

They now delegate to the top-level `requirements-qwen.txt` or
`requirements-voice.txt`, so use the top-level files for fresh installs.

If PyTorch needs a machine-specific CPU/CUDA build, install the matching
`torch` wheel first using the PyTorch command for that machine, then run the
requirements install. The pinned requirement uses the base version and does not
encode the local `+cpu` or `+cu*` build suffix.

Set the actual paths in `config/local.env`:

```bash
QWEN_PYTHON="${HOME}/miniconda3/envs/qwen/bin/python"
VOICE_PYTHON="${HOME}/miniconda3/envs/voice/bin/python"
```

## Ollama

Install Ollama, start it, and pull the embedding model:

```bash
ollama pull nomic-embed-text
ollama list
```

The default embedding config is:

```text
EMBED_PROVIDER=ollama
EMBED_MODEL=nomic-embed-text
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

If using a portable Ollama bundle, set:

```bash
OLLAMA_BIN="/path/to/ollama"
OLLAMA_HOME="/path/to/ollama-home"
OLLAMA_MODELS="/path/to/ollama-home/models"
```

## DeepSeek API

Create `config/local.env` and add:

```bash
OPENAI_API_KEY="sk-your-deepseek-api-key"
OPENAI_BASE_URL="https://api.deepseek.com"
CHAT_PROVIDER="openai"
CHAT_MODEL="deepseek-v4-pro"
```

`config/local.env` is ignored by Git.

## Unitree G1 Network

Set the robot network interface:

```bash
UNITREE_NETWORK_INTERFACE="enp8s0"
UNITREE_DOMAIN_ID="0"
UNITREE_ENABLE="1"
```

The startup script disables G1 audio/action execution automatically if the
configured network interface is not active.

## CycloneDDS / Unitree DDS

The repo has two Unitree DDS paths:

- Python Unitree SDK under `deps/qwen_ros_node_edg_tts/third_party/unitree_sdk2_python`
  declares `cyclonedds==0.10.2`.
- C++ Unitree SDK under `deps/unitree_g1_action_classifier_package/unitree_sdk2`
  links the bundled `ddsc` and `ddscxx` libraries.

Install the Python SDK dependency in the main pipeline environment:

```bash
${QWEN_PYTHON:-$HOME/miniconda3/envs/qwen/bin/python} -m pip install -e deps/qwen_ros_node_edg_tts/third_party/unitree_sdk2_python
```

The Python SDK generates CycloneDDS XML at runtime and binds DDS to
`UNITREE_NETWORK_INTERFACE`. The integrated pipeline uses Unitree DDS for G1
audio playback, lights, and action execution. If the configured interface is
missing, `scripts/run_pipeline.sh` disables Unitree execution instead of
starting with a bad DDS route.

For cross-host discovery or a fixed peer, add `CYCLONEDDS_URI` in
`config/local.env`:

```bash
CYCLONEDDS_URI='<CycloneDDS><Domain><General><NetworkInterfaceAddress>enp8s0</NetworkInterfaceAddress></General><Discovery><Peers><Peer address="ROBOT_OR_HOST_IP"/></Peers></Discovery></Domain></CycloneDDS>'
```

Check DDS setup:

```bash
ip -o link show "$UNITREE_NETWORK_INTERFACE"
${QWEN_PYTHON:-$HOME/miniconda3/envs/qwen/bin/python} -c "import cyclonedds; print('cyclonedds ok')"
ldd deps/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example | rg 'ddsc|ddscxx|not found'
```

If DDS fails, also inspect `/tmp/cdds.LOG` when CycloneDDS tracing is enabled
by the Unitree SDK.

## Unitree Action Runner

Build the G1 action runner:

```bash
cd deps/unitree_g1_action_classifier_package/unitree_sdk2
mkdir -p build
cd build
cmake ..
make -j
```

Expected output:

```text
deps/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example
```

Override if needed:

```bash
QWEN_ACTION_RUNNER="/path/to/g1_arm_action_example"
```

## Wake-Word Model Files

The repository includes wake-word text config:

```text
deps/SURF2026_VoiceModule-main/models/kws/keywords.txt
deps/SURF2026_VoiceModule-main/models/kws/tokens.txt
```

The ONNX model binaries are intentionally not committed. Restore or download
the expected files under the same directory:

```text
encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx
decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx
joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx
```

## Local Configuration Template

Example `config/local.env`:

```bash
cp config/local.env.example config/local.env
```

Then edit the copied file for `OPENAI_API_KEY`, Python paths, and robot network
settings.

## Validate

Run:

```bash
./scripts/check_pipeline.sh
```

Then start:

```bash
./scripts/run_pipeline.sh --mode wake
```
