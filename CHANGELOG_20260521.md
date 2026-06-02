# 2026-05-21 Update Log

This document archives the SURF -> Qwen -> Unitree G1 pipeline changes made on
2026-05-21.

## Voice Pipeline

- Forced integrated voice input to use the robot microphone path by default.
- Kept `VOICE_AUDIO_SOURCE=robot` in the integrated pipeline.
- Removed silent/local fallback behavior from the runtime path used by the G1
  pipeline, so robot mic failures are visible instead of being hidden.
- Set wake ack text:
  - Chinese wake word -> `我在`
  - English wake word -> `here i am`
- Updated ASR timeout logic:
  - `_asr_deadline` remains an 8 second no-speech fallback.
  - When speech is detected by VAD, `_asr_deadline` is cancelled.
  - When speaker embedding is detected, `_asr_deadline` is also cancelled.
  - After speech starts, recording ends by VAD silence instead of a hard 8
    second cutoff.
- Set VAD silence threshold to 1.5 seconds:
  - `VOICE_FRAME_MS=20`
  - `VOICE_VAD_SILENCE_FRAMES=75`
- Kept VAD holdoff at 4 seconds to avoid cutting off the wake ack playback.
- Reduced FunASR / ModelScope console noise in journald by suppressing model
  stdout/stderr unless `VOICE_ASR_VERBOSE=1`.

## Wake State And Lights

- Moved G1 light control out of the ROS context node's direct DDS path.
- Centralized light execution in `unitree_audio_player.py`.
- Added periodic light refresh so official/default robot LED behavior is less
  likely to override custom colors.
- Changed light behavior to event-driven instead of a fixed wake countdown:
  - Standby/default: blue
  - Wake / waiting command: red
  - Valid ASR received / thinking: blinking green
  - Formal reply playback: blue
  - Playback finished: blue
  - Empty/ignored ASR or failed request: blue
- Wake ack playback no longer switches light to blue.
- `thinking_ack` playback also does not switch light to blue.
- Added blink support in light command payload:
  - `effect=solid`
  - `effect=blink`

## Wake Ack Action

- Added a wake ack action that runs when the robot replies `我在`.
- Mapped "胸前挥手" request to the closest official action:
  - Chinese label: `面前挥手`
  - Official name: `face wave`
  - Action ID: `25`
- Added configuration:
  - `SURF_QWEN_WAKE_ACK_ACTION_ENABLE=1`
  - `SURF_QWEN_WAKE_ACK_ACTION_ID=25`
  - `SURF_QWEN_WAKE_ACK_ACTION_LABEL=面前挥手`
- Wake ack action runs directly through the Unitree action runner, not through
  Qwen action classification.

## Thinking Ack

- Added a short acknowledgement after valid ASR is accepted:
  - Text: `收到`
- Added configuration:
  - `SURF_QWEN_THINKING_ACK_ENABLE=1`
  - `SURF_QWEN_THINKING_ACK_TEXT=收到`
- Flow is now:

```text
wake word -> red light -> "我在" + face wave
command ASR accepted -> blinking green + "收到"
Qwen/RAG/DeepSeek reply ready -> formal reply playback -> blue
```

## Actions

- Confirmed official G1 action IDs used by the local classifier:
  - `face wave`: 25
  - `high wave`: 26
- Kept keyword-first action behavior enabled for reply actions.
- Kept normal reply action flow separate from wake ack action.

## Logging

- Added per-session pipeline logging under:

```text
logs/YYYYMMDD_HHMMSS_sNNN/
```

- Session logs include stages such as:
  - `wake`
  - `asr_started`
  - `asr_deadline_cancelled`
  - `speaker_id`
  - `audio_saved`
  - `asr_result`
  - `asr_received`
  - `wake_command_started`
  - `thinking`
  - `thinking_ack_ready`
  - `qwen_reply`
  - `tts_ready`
  - `tts_play_started`
  - `tts_play_finished`
  - `action_result`
  - `wake_ack_action_result`
  - `session_end`
- Added speaker similarity score logging:
  - `label`
  - `score`
- Added RAG / LLM timing fields to chat responses and session logs.
- Current session archive files:
  - `pipeline.log`
  - `audio.wav`

## Project Cleanup

- Added `PROJECT_CLEANUP.md` to document source files, generated runtime files,
  and test archives.
- Added `scripts/clean_workspace.sh`.
- Default cleanup removes:
  - `__pycache__/`
  - `.pytest_cache/`
  - `*.pyc`
  - `*.pyo`
- Optional cleanup modes:

```bash
./scripts/clean_workspace.sh --runtime
./scripts/clean_workspace.sh --logs
```

- Updated README files for:
  - correct workspace path
  - current startup command
  - current voice timing
  - current light states
  - cleanup instructions

## Important Current Commands

Start full pipeline:

```bash
cd /home/louisxx/ProjectArchive/surf/2526/surf_qwen_clean_workspace
./scripts/run_pipeline.sh --mode wake
```

Stop full pipeline:

```bash
cd /home/louisxx/ProjectArchive/surf/2526/surf_qwen_clean_workspace
./scripts/stop_pipeline.sh
```

Follow logs:

```bash
journalctl --user -u surf-voice-runtime -f
journalctl --user -u surf-qwen-node -f
journalctl --user -u surf-qwen-audio-player -f
```

Check workspace:

```bash
cd /home/louisxx/ProjectArchive/surf/2526/surf_qwen_clean_workspace
./scripts/check_pipeline.sh
```

## Main Files Changed

Integrated workspace:

```text
config/default.env
project_config.py
qwen_surf_context_node.py
surf_voice_runtime.py
unitree_audio_player.py
pipeline_log/pipeline_logger.py
scripts/clean_workspace.sh
README.md
PROJECT_CLEANUP.md
```

SURF voice module:

```text
asr/asr_engine.py
config/default.env
config/voice_config.py
ros_nodes/voice_pipeline_node.py
standalone_test.py
voice_id/speaker_database.py
README.md
```

## Current Expected Behavior

```text
1. User says wake word.
2. Robot turns red.
3. Robot says "我在".
4. Robot runs face wave / action ID 25.
5. User speaks command.
6. ASR accepts command.
7. Robot blinks green and says "收到".
8. Qwen/RAG/DeepSeek generates reply.
9. Robot plays formal reply in blue light.
10. Robot remains blue after playback.
```

