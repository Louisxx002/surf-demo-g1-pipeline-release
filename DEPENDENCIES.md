# Dependency Manifest

See [ENVIRONMENT.md](ENVIRONMENT.md) for installation commands. This file
summarizes what is tracked in Git and what must be restored locally.

## Tracked Source Dependencies

```text
deps/SURF2026_VoiceModule-main/             SURF wake/VAD/ASR/speaker module
deps/qwen_ros_node_edg_tts/                 Unitree SDK Python subtree and legacy Qwen node files
deps/unitree_g1_action_classifier_package/  Unitree action support source and SDK files
xjtlu-rag-system/                           RAG service, knowledge DB, and vector index DB
```

## DDS Dependencies

```text
Python Unitree SDK:
  deps/qwen_ros_node_edg_tts/third_party/unitree_sdk2_python
  requires cyclonedds==0.10.2

C++ Unitree SDK:
  deps/unitree_g1_action_classifier_package/unitree_sdk2
  links bundled ddsc and ddscxx libraries
```

The action runner build output is intentionally not tracked. Rebuild it locally
so the executable can resolve the Unitree/CycloneDDS shared libraries for the
current machine architecture.

## Intentionally Not Tracked

```text
Conda environments:
  $HOME/miniconda3/envs/voice/bin/python
  $HOME/miniconda3/envs/qwen/bin/python

Large runtime assets:
  deps/ollama/
  deps/ollama-home/
  deps/Qwen3.5-0.8B/
  deps/unitree_g1_action_classifier_package/unitree_sdk2/build/
  deps/SURF2026_VoiceModule-main/models/kws/*.onnx

Generated runtime files:
  __pycache__, .pytest_cache, runtime logs, temporary TTS files

Secrets:
  config/local.env
```

`config/default.env` contains safe defaults. Put local paths and secrets in
`config/local.env`.
