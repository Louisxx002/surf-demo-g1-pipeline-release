# SURF Qwen Clean Workspace

Integrated workspace for the SURF voice module, XJTLU RAG, TTS playback, and
Unitree G1 action execution.

For a fresh machine setup, read [REPRODUCIBILITY.md](REPRODUCIBILITY.md). This
repo excludes large runtime assets and local secrets, so clone-only is not
enough for the full robot demo.

## Pipeline

```text
SURF voice runtime
  -> /audio_msg
  -> qwen_surf_context_node.py
  -> qwen_server.py
  -> XJTLU RAG / Ollama embedding / DeepSeek reply + action
  -> Edge TTS wav
  -> Unitree action runner
```

## Current Runtime Behavior

Voice timing:

```text
wake word -> wake ack "我在" -> record command -> 1.5s silence -> ASR -> thinking ack "收到，我在思考" -> DeepSeek/RAG
```

The ASR hard deadline is only a no-speech fallback. Once speech is detected by
VAD or speaker embedding, the deadline is cancelled and VAD controls the end of
recording.

Light states:

```text
standby                 -> blue
wake / waiting command  -> red
ASR accepted / thinking -> green
reply playback          -> blue
playback finished       -> blue
```

## Main Commands

Start the full pipeline:

```bash
cd <repo-root>
./scripts/run_pipeline.sh --mode wake
```

Stop the pipeline:

```bash
./scripts/stop_pipeline.sh
```

Check configuration and syntax:

```bash
./scripts/check_pipeline.sh
```

Clean generated local files:

```bash
./scripts/clean_workspace.sh
./scripts/clean_workspace.sh --runtime
./scripts/clean_workspace.sh --logs
```

Follow logs:

```bash
./scripts/tail_pipeline_logs.sh all
./scripts/tail_pipeline_logs.sh rag
./scripts/tail_pipeline_logs.sh qwen
./scripts/tail_pipeline_logs.sh voice
```

Monitor ASR topic:

```bash
./scripts/monitor_audio_msg.sh
```

## Current Backend

The default configured backend is RAG:

```text
QWEN_REPLY_BACKEND=rag
CHAT_PROVIDER=openai
CHAT_MODEL=deepseek-v4-pro
EMBED_PROVIDER=ollama
EMBED_MODEL=nomic-embed-text
```

Put machine-specific values and secrets in `config/local.env`. This file is
loaded after `config/default.env` and is ignored by git:

```bash
cat > config/local.env <<'EOF'
OPENAI_API_KEY="sk-your-deepseek-api-key"
UNITREE_NETWORK_INTERFACE="enp8s0"
QWEN_PYTHON="${HOME}/miniconda3/envs/qwen/bin/python"
EOF
```

Switch reply backend:

```bash
./scripts/env_set.sh QWEN_REPLY_BACKEND rag
./scripts/env_set.sh QWEN_REPLY_BACKEND local
./scripts/env_set.sh QWEN_REPLY_BACKEND dashscope
```

## Important Paths

```text
config/default.env             Safe default runtime configuration
config/local.env               Local overrides and API keys, not committed
xjtlu-rag-system/              XJTLU RAG service and knowledge index
runtime/                       Generated status and TTS files
logs/                          Per-session pipeline archives
deps/                          External runtime dependencies and vendored source
scripts/                       Startup, stop, check, and log scripts
DEPENDENCIES.md                Bundled dependency manifest
PROJECT_CLEANUP.md             What is source vs generated output
CHANGELOG_20260521.md          Archived update summary for 2026-05-21
```

## External Dependencies

The GitHub repository intentionally does not include heavyweight local runtime
artifacts such as conda environments, Ollama binaries, Ollama model cache, local
Qwen model weights, generated build directories, logs, or TTS output. Install or
restore them locally, then point `config/local.env` at those paths when needed.

Expected paths in the current deployment:

```text
SURF_ROOT=deps/SURF2026_VoiceModule-main
QWEN_ROOT=deps/qwen_ros_node_edg_tts
QWEN_ACTION_ROOT=deps/unitree_g1_action_classifier_package
OLLAMA_BIN=deps/ollama/bin/ollama
OLLAMA_HOME=deps/ollama-home
```

Python interpreters are external environment dependencies:

```text
QWEN_PYTHON=$HOME/miniconda3/envs/qwen/bin/python
VOICE_PYTHON from deps/SURF2026_VoiceModule-main/config/default.env
```

The expected Ollama embedding model is `nomic-embed-text`:

```bash
ollama pull nomic-embed-text
```
