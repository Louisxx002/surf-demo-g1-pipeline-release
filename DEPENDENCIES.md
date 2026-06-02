# Bundled Dependency Manifest

This workspace archives project/runtime dependencies under `deps/` so the main
SURF -> Qwen pipeline can run from one directory.

## Bundled

```text
deps/SURF2026_VoiceModule-main/             SURF wake/VAD/ASR/speaker module
deps/qwen_ros_node_edg_tts/                 Unitree SDK Python subtree and legacy Qwen node files
deps/unitree_g1_action_classifier_package/  Action classifier source and Unitree G1 action runner
deps/Qwen3.5-0.8B/model/                    Local Qwen model for QWEN_REPLY_BACKEND=local
deps/ollama/                                Local Ollama executable and runtime libraries
deps/ollama-home/models/                    Current Ollama embedding model cache
```

## Intentionally Not Bundled

```text
Conda environments:
  /home/louisxx/miniconda3/envs/voice/bin/python
  /home/louisxx/miniconda3/envs/qwen/bin/python

Generated runtime files:
  __pycache__, .pytest_cache, runtime logs, temporary TTS files
```

`config/default.env` points to the bundled dependency paths by default. Override
those variables before running scripts if you need to use an external install.
