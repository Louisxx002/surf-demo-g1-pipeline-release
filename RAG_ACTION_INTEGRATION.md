# XJTLU RAG + Action Pipeline

This workspace can run the XJTLU RAG backend while keeping the existing SURF
voice, TTS, action classifier, and Unitree action execution pipeline.

## Flow

```text
SURF ASR /audio_msg
  -> llm_surf_context_node.py
  -> llm_server.py /infer
  -> xjtlu-rag-system /chat when LLM_REPLY_BACKEND=rag
  -> edge_tts wav generation
  -> existing action classifier and Unitree runner
```

The GitHub RAG bridge publishes `/xjtlu_reply`, but this workspace does not use
that topic for action execution. Instead, `llm_server.py` calls the RAG HTTP API
directly so the existing action path receives the final reply unchanged.

## Enable RAG

```bash
cd <repo-root>
./scripts/env_set.sh LLM_REPLY_BACKEND rag
./scripts/run_pipeline.sh
```

To switch back to the current local Qwen model:

```bash
./scripts/env_set.sh LLM_REPLY_BACKEND local
```

## Model Provider

The configured setup uses DeepSeek for chat and Ollama for local embeddings:

```bash
CHAT_PROVIDER=openai
OPENAI_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-v4-pro
EMBED_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
EMBED_MODEL=bge-m3
```

`OPENAI_API_KEY` is stored in `config/default.env` locally. Do not commit or
share that file.

To update the DeepSeek/OpenAI-compatible chat backend:

```bash
./scripts/env_set.sh CHAT_PROVIDER openai
./scripts/env_set.sh OPENAI_BASE_URL https://api.deepseek.com
./scripts/env_set.sh OPENAI_API_KEY sk-your-key
./scripts/env_set.sh CHAT_MODEL deepseek-v4-pro
```

Embedding still needs Ollama running with the configured embedding model:

```bash
./deps/ollama/bin/ollama pull bge-m3
```
