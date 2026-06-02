# Project Structure

## Core

- `qwen_server.py`: HTTP server. Loads local Qwen model, generates replies, and creates Edge TTS mp3 files.
- `qwen_ros_node_edg_tts.py`: ROS2 node. Subscribes to `/audio_msg`, applies wake-word/listen-mode filtering, calls the Qwen server, converts mp3 to wav, and optionally sends the reply through the G1 action classifier/runner.
- `asr_dds_to_ros_bridge.py`: Safe one-way bridge from Unitree DDS `rt/audio_msg` to ROS2 `/audio_msg`.
- `unitree_audio_player.py`: Watches `runtime/tts.wav` and plays it through Unitree DDS audio.
- `project_config.py`: Centralized environment-backed configuration.
- `wav.py`: WAV loading and audio streaming helpers.

## Configuration

- `config/default.env`: Default runtime configuration.
- `requirements.txt`: Python dependencies for the Qwen/TTS node.

Important runtime knobs in `config/default.env`:

- `QWEN_AUDIO_TOPIC`: ROS2 ASR text topic, default `/audio_msg`.
- `QWEN_WAKE_WORDS`: comma-separated wake words used by the ROS node.
- `QWEN_ALWAYS_LISTEN`: `1` for plain listen mode, `0` for wake-word mode.
- `UNITREE_NETWORK_INTERFACE`: robot DDS network interface, default `enp8s0`.
- `QWEN_ACTION_ENABLE`: enable reply-to-action classification.
- `QWEN_ACTION_EXECUTE`: execute the classified action on the robot. Set to `0` for dry-run.
- `QWEN_ACTION_AUTO_RELEASE`: when enabled, run release action `99` and retry once if the runner reports `arm_holding_release_required`.

## Scripts

- `scripts/run_server.sh`: Start the Qwen HTTP server.
- `scripts/run_asr_bridge.sh`: Start the safe Unitree DDS ASR to ROS2 bridge.
- `scripts/run_full_pipeline.sh`: Start the full voice chain in one command.
- `scripts/stop_full_pipeline.sh`: Stop the full voice chain.
- `scripts/run_ros_node.sh`: Start the ROS2 text-to-reply node and, unless `QWEN_AUTOSTART_ASR_BRIDGE=0`, start the ASR DDS bridge in the background.
- `scripts/run_audio_player.sh`: Start Unitree audio playback.
- `scripts/monitor_audio_msg.sh`: Watch incoming ASR text on `/audio_msg`.
- `scripts/monitor_ros_logs.sh`: Watch ROS node logs.
- `scripts/check_project.sh`: Fast syntax/config check.
- `scripts/check_full_pipeline.sh`: Broader local pipeline check.

## Runtime

- `runtime/`: Generated mp3/wav files and ROS logs. Contents are disposable.
- `runtime/ros_logs/`: ROS log output. Contents are disposable.
- `runtime/asr_bridge.log`: ASR bridge log when it is autostarted by `run_ros_node.sh`.
- `runtime/asr_bridge.pid`: PID file used to stop the autostarted ASR bridge.

## Third Party

- `third_party/unitree_sdk2_python/`: Vendored Unitree SDK2 Python package needed for robot audio/DDS access.
