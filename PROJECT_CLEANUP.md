# Project Cleanup Notes

This workspace has three categories of files.

## Source Files

Keep these under version control:

```text
config/
pipeline_log/
scripts/
xjtlu-rag-system/*.py
deps/SURF2026_VoiceModule-main/
deps/qwen_ros_node_edg_tts/
deps/unitree_g1_action_classifier_package/
deps/Qwen3.5-0.8B/model/
deps/ollama/
deps/ollama-home/models/
project_config.py
qwen_server.py
qwen_surf_context_node.py
surf_ros_bridge.py
surf_voice_runtime.py
unitree_audio_player.py
wav.py
README.md
PACKAGING.md
RAG_ACTION_INTEGRATION.md
```

## Generated Runtime Files

These are created while the pipeline runs and are safe to regenerate:

```text
runtime/status.json
runtime/surf_context_status.json
runtime/tts.mp3
runtime/tts.wav
runtime/tts_play_context.json
runtime/wake_light_command.json
runtime/xjtlu_chat_memory.db
runtime/ros_logs/
```

Bundled dependencies intentionally exclude generated caches, `.git` folders,
runtime logs, and the action-classifier `.venv`. Rebuild or point
`QWEN_ACTION_PYTHON` at an existing Python environment if that package needs
additional Python dependencies.

## Test Archives

Each wake session writes a directory under:

```text
logs/YYYYMMDD_HHMMSS_sNNN/
```

These archives usually contain:

```text
pipeline.log
audio.wav
```

They are ignored by git and should be kept while debugging real robot behavior.
Delete them only when you no longer need test evidence.

## Cleaning

Default cleanup removes Python and pytest caches only:

```bash
./scripts/clean_workspace.sh
```

Clean current runtime files:

```bash
./scripts/stop_pipeline.sh
./scripts/clean_workspace.sh --runtime
```

Clean session archives:

```bash
./scripts/clean_workspace.sh --logs
```
