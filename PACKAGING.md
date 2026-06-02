# Packaging Notes

Build a relocatable release bundle with:

```bash
cd /home/louisxx/ProjectArchive/surf/2526/surf_qwen_clean_workspace
./scripts/build_release_bundle.sh --output /home/louisxx/surf_qwen_release --name surf_qwen_bundle --tar
```

What the bundle includes:

- `surf_qwen_workspace`
- `SURF2026_VoiceModule-main`
- `qwen_ros_node_edg_tts` Unitree SDK subtree
- `unitree_g1_action_classifier_package` source and runner
- Qwen local model directory
- SURF ASR model directory
- voiceprint cache for offline startup

What remains external:

- a working `voice` Python environment
- a working `qwen` Python environment
- ROS2 Jazzy and Unitree runtime prerequisites

To run the bundle on another machine:

1. Unpack it.
2. Edit `bundle.env` and set `VOICE_PYTHON` and `QWEN_PYTHON` to executable
   Python paths.
3. Run `./run.sh`.

The action-classifier path is derived from `QWEN_PYTHON` by default, so a
separate `.venv` for the classifier is not required in the release bundle.

This keeps the source tree and model paths relocatable while leaving the
machine-specific Python environments explicit.
