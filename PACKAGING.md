# Packaging Notes

Build a relocatable release bundle with:

```bash
cd <repo-root>
./scripts/build_release_bundle.sh --output ./release-output --name surf_llm_bundle --tar
```

What the bundle includes:

- `surf_llm_workspace`
- `SURF2026_VoiceModule-main`
- `qwen_ros_node_edg_tts` Unitree SDK subtree
- `unitree_g1_action_classifier_package` source and runner
- Qwen local model directory
- SURF ASR model directory
- voiceprint cache for offline startup

What remains external:

- a working `voice` Python environment
- a working `llm` Python environment
- ROS2 Jazzy and Unitree runtime prerequisites
- API keys, which must be set on the target machine

To run the bundle on another machine:

1. Unpack it.
2. Edit `bundle.env` and set `VOICE_PYTHON` and `LLM_PYTHON` to executable
   Python paths.
3. Set `OPENAI_API_KEY` in the shell or copy the value from
   `bundle.env.example` into `bundle.env`.
4. Run `./run.sh`.

The action-classifier path is derived from `LLM_PYTHON` by default, so a
separate `.venv` for the classifier is not required in the release bundle.

This keeps the source tree and model paths relocatable while leaving the
machine-specific Python environments explicit.

The bundle builder intentionally excludes local secrets and runtime outputs from
the copied workspace, including `config/local.env`, `.env`, `runtime/`, logs,
generated wav/mp3 files, and duplicated heavyweight `deps/` content. Use
`config/local.env.example` in the source tree as the template for a fresh clone.
