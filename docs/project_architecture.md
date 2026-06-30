# SURF LLM Clean Workspace Architecture

本文档基于当前仓库源码建立项目理解，重点覆盖入口、层级架构、配置、依赖、数据路径和从运行命令到机器人执行的调用链。本文只描述当前集成工作区；`deps/` 中还包含历史/外部包，已单独标注。

## 1. 项目定位

当前项目是一个面向 Unitree G1 的语音交互集成工作区：

```text
机器人/USB 麦克风音频
-> SURF 语音运行时
-> ROS2 话题
-> LLM/RAG 编排节点
-> LLM server / XJTLU RAG / DeepSeek
-> Edge TTS
-> Unitree G1 扬声器、灯光、手臂动作
```

主链路在根目录实现，关键入口是：

- `scripts/run_pipeline.sh`
- `surf_voice_runtime.py`
- `surf_ros_bridge.py`
- `llm_surf_context_node.py`
- `llm_server.py`
- `unitree_audio_player.py`
- `xjtlu-rag-system/app.py`
- `deps/unitree_g1_action_classifier_package/arm_action_classifier/arm_action_classifier.py`
- `deps/unitree_g1_action_classifier_package/unitree_sdk2/example/g1/high_level/g1_arm_action_example.cpp`

没有发现 Isaac Sim、MuJoCo、ROS launch 文件作为当前项目入口。仓库中存在 ROS2 Python 节点，但没有 `.launch.py` 或 `.launch` 启动描述文件。

## 2. 入口文件和启动命令

### 2.1 主启动入口

`scripts/run_pipeline.sh` 是完整集成链路入口。

常用命令：

```bash
./scripts/run_pipeline.sh --mode wake
./scripts/run_pipeline.sh --mode listen
```

它会：

1. `source config/default.env`，并通过该文件尾部加载 `config/local.env`。
2. `source /opt/ros/jazzy/setup.bash`。
3. 调用 `resolve_unitree_availability()` 检查 `UNITREE_ENABLE` 和 `UNITREE_NETWORK_INTERFACE`。
4. 停止旧的 systemd user services。
5. 通过 `systemd-run --user` 启动以下服务：
   - `surf-ros-bridge.service` -> `scripts/run_surf_ros_bridge.sh`
   - `surf-voice-runtime.service` -> `scripts/run_surf_voice_runtime.sh`
   - `surf-llm-ollama.service` -> `scripts/run_ollama_server.sh`，仅 `LLM_REPLY_BACKEND=rag`
   - `surf-llm-rag.service` -> `scripts/run_rag_server.sh`，仅 `LLM_REPLY_BACKEND=rag`
   - `surf-llm-server.service` -> `scripts/run_llm_server.sh`
   - `surf-llm-node.service` -> `scripts/run_surf_context_node.sh`
   - `surf-llm-audio-player.service` -> `scripts/run_audio_player.sh`

### 2.2 单组件入口

- `scripts/run_surf_voice_runtime.sh`
  - 设置 `PYTHONPATH="${SURF_ROOT}:${WORKSPACE_ROOT}"`。
  - 运行 `VOICE_PYTHON surf_voice_runtime.py`。
  - 当前集成链路使用这个根目录运行时，而不是直接运行 SURF 子模块的 ROS node。

- `scripts/run_surf_ros_bridge.sh`
  - 设置 ROS2 环境和 `ROS_LOG_DIR=runtime/ros_logs`。
  - 运行 `python3 surf_ros_bridge.py`。

- `scripts/run_llm_server.sh`
  - 设置 `PYTHONPATH="${WORKSPACE_ROOT}:${LLM_ROOT}/third_party/unitree_sdk2_python"`。
  - 运行 `LLM_PYTHON -m uvicorn llm_server:app --host $LLM_SERVER_HOST --port $LLM_SERVER_PORT`。

- `scripts/run_surf_context_node.sh`
  - 设置 ROS2 环境、`ROS_LOG_DIR`、`PYTHONPATH`。
  - 运行 `LLM_PYTHON llm_surf_context_node.py`。

- `scripts/run_audio_player.sh`
  - 设置 Unitree Python SDK 的 `PYTHONPATH`。
  - 运行 `LLM_PYTHON unitree_audio_player.py`。

- `scripts/run_rag_server.sh`
  - 进入 `xjtlu-rag-system/`。
  - 运行 `LLM_PYTHON -m uvicorn app:app --host $RAG_SERVER_HOST --port $RAG_SERVER_PORT`。

- `scripts/run_ollama_server.sh`
  - 设置 `OLLAMA_HOST`、`OLLAMA_MODELS`。
  - 运行 `OLLAMA_BIN serve`。

### 2.3 管理和调试脚本

- `scripts/stop_pipeline.sh`：停止所有相关 systemd user services，并 `pkill` 旧 ASR bridge。
- `scripts/check_pipeline.sh`：检查关键文件、shell 语法和 Python AST 语法。
- `scripts/tail_pipeline_logs.sh`：按组查看 `journalctl --user` 日志。
- `scripts/monitor_audio_msg.sh`：`ros2 topic echo /audio_msg`。
- `scripts/env_set.sh`：写入或更新 `config/local.env` 的键值。
- `scripts/setup_conda_envs.sh`：创建 `llm` 和 `voice` conda 环境并安装依赖。
- `scripts/build_release_bundle.sh`：打包可迁移 bundle，包含源码、模型、Unitree SDK、RAG 数据库等。

### 2.4 其他入口

- `xjtlu-rag-system/ingest.py`
  - CLI：`python ingest.py --source-db ... --rag-db ... --reset`
  - 函数：`main()`、`build_embedding_text()`
  - 用于从 `xjtlu_knowledge.db` 重建 `rag_index.db`。

- `xjtlu-rag-system/ros_bridge.py`
  - ROS2 辅助桥接节点 `XjtluVoiceBridge`。
  - 订阅 `/wake_word_event`、`/audio_msg`，发布 `/xjtlu_reply`。
  - 当前主链路没有由 `scripts/run_pipeline.sh` 启动它。

- `deps/qwen_ros_node_edg_tts/asr_dds_to_ros_bridge.py`
  - CLI 参数：`--network`、`--domain-id`、`--dds-topic`、`--ros-topic`。
  - 类：`AsrBridge`
  - 函数：`parse_args()`、`is_asr_text_payload()`、`main()`
  - 将 Unitree DDS `rt/audio_msg` 转成 ROS2 `/audio_msg`。当前主链路中 `LLM_AUTOSTART_ASR_BRIDGE=0`，并由 SURF 作为 ASR 来源。

- `deps/unitree_g1_action_classifier_package/arm_action_classifier/arm_action_classifier.py`
  - CLI：`arm_action_classifier.py TEXT --backend qwen|hf|keyword --execute --network IFACE --runner PATH`
  - 函数：`build_parser()`、`main()`、`classify_keyword()`、`classify_qwen()`、`classify_hf()`、`execute_action()`

- `deps/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example`
  - C++ 编译产物，被 Python 侧作为真机动作 runner 调用。
  - 源码：`deps/unitree_g1_action_classifier_package/unitree_sdk2/example/g1/high_level/g1_arm_action_example.cpp`

## 3. 分层架构

### 3.1 数据输入层

核心职责：采集机器人或本机麦克风 PCM 音频。

- `deps/SURF2026_VoiceModule-main/audio/robot_mic_capture.py`
  - 类：`RobotMicCapture`
  - 方法：`start()` 创建 UDP socket，加入组播 `VOICE_ROBOT_MIC_GROUP:VOICE_ROBOT_MIC_PORT`，绑定 `VOICE_ROBOT_MIC_IF`。
  - 方法：`_recv_loop()` 收包并按 `CONFIG.frame_bytes` 切分成帧，推入 `AudioBus`。

- `deps/SURF2026_VoiceModule-main/audio/mic_capture.py`
  - 类：`MicCapture`
  - 用本地 sounddevice/PyAudio 风格输入采集本机麦克风。

- `deps/SURF2026_VoiceModule-main/audio/audio_bus.py`
  - 类：`AudioBus`
  - 方法：`register()`、`push()`、`get_buffer()`
  - 是线程安全 PCM 广播总线，同时保存最近音频回溯 buffer。

- `deps/SURF2026_VoiceModule-main/tools/stream_usb_mic.py`
  - 工具入口，用于从机器人端把 USB 麦音频以 UDP 方式转发给 PC/WSL。

### 3.2 感知/语音层

核心职责：唤醒词、VAD、ASR、声纹识别。

- `surf_voice_runtime.py`
  - 类：`SurfVoiceRuntime`
  - 方法：`start()` 启动 wake word 和 mic。
  - 方法：`spin()` 检查 ASR deadline。
  - 回调：`_on_wake()`、`_on_vad()`、`_on_asr()`、`_on_embedding()`
  - 它组合了 SURF 子模块中的 `AudioBus`、`VADEngine`、`ChineseWakeWordDetector`/`WakeWordDetector`、`ASREngine`、`VoiceprintRecognizer`、`SpeakerDatabase`。

- `deps/SURF2026_VoiceModule-main/wake_word/chinese_wake_word_detector.py`
  - 类：`ChineseWakeWordDetector`
  - 基于 sherpa-onnx KWS 模型，模型目录由 `VOICE_KWS_MODEL_DIR` 控制。

- `deps/SURF2026_VoiceModule-main/wake_word/wake_word_detector.py`
  - 类：`WakeWordDetector`
  - openWakeWord 封装。

- `deps/SURF2026_VoiceModule-main/vad/vad_engine.py`
  - 类：`VADEngine`
  - 方法：`process_frame()` 输出语音/静音状态，静音帧数由 `VOICE_VAD_SILENCE_FRAMES` 控制。

- `deps/SURF2026_VoiceModule-main/asr/asr_engine.py`
  - 类：`ASREngine`
  - 方法：`start_recording()`、`push_audio()`、`stop_and_transcribe()`
  - 使用 FunASR `AutoModel`，模型由 `VOICE_ASR_MODEL` 控制。

- `deps/SURF2026_VoiceModule-main/voice_id/voiceprint_recognizer.py`
  - 类：`VoiceprintRecognizer`
  - 提取 speaker embedding。

- `deps/SURF2026_VoiceModule-main/voice_id/speaker_database.py`
  - 类：`SpeakerDatabase`
  - 方法：`identify_with_score()`，按余弦相似度维护说话人标签。

### 3.3 ROS/DDS 桥接层

核心职责：把非 ROS 事件或 Unitree DDS 转成 ROS2 话题。

- `surf_voice_runtime.py`
  - 类：`UdpEventSink`
  - 方法：`publish(topic, msg_type, data)`
  - 将 `/wake_word_event`、`/vad_state`、`/speaker_id`、`/audio_msg` 编成 UDP JSON 发给本机 `SURF_BRIDGE_HOST:SURF_BRIDGE_PORT`。

- `surf_ros_bridge.py`
  - 类：`SurfRosBridge`
  - 方法：`_poll()` 从 UDP socket 读事件。
  - 根据 `type=bool|string` 动态创建 ROS2 publisher，发布到事件指定 topic。

- `deps/qwen_ros_node_edg_tts/asr_dds_to_ros_bridge.py`
  - 类：`AsrBridge`
  - 方法：`handle_unitree_msg()`
  - 用 `ChannelFactoryInitialize()` 和 `ChannelSubscriber()` 订阅 Unitree DDS `rt/audio_msg`，转发 ROS2 `/audio_msg`。
  - 当前集成默认不启用。

### 3.4 运动生成/规划层

本项目没有连续轨迹规划、导航规划、全身运动生成、retarget 或 IK 模块。当前“运动生成”是语义层动作选择：把 LLM 回复或用户文本映射到 Unitree G1 官方预置动作 ID。

- `xjtlu-rag-system/chat_engine.py`
  - 数据类：`ArmAction`
  - 常量：`ACTIONS`
  - 函数：`_normalize_action()`、`chat()`
  - RAG/DeepSeek 在回答 JSON 中返回动作标签、置信度和原因。

- `llm_surf_context_node.py`
  - 方法：`_classification_from_deepseek_action()`
  - 方法：`run_reply_action()`、`_run_reply_action_locked()`
  - 优先使用 RAG 返回的 `action`；若没有，根据 `LLM_ACTION_KEYWORD_FIRST` 和 `LLM_ACTION_BACKEND` 调用动作分类器。

- `deps/unitree_g1_action_classifier_package/arm_action_classifier/arm_action_classifier.py`
  - 常量：`ACTIONS`、`REPLY_INTENTS`
  - 函数：`classify_keyword()`、`classify_reply_rules()`、`classify_qwen()`、`classify_hf()`
  - 输出 `ClassificationResult`，字段包含 `label`、`official_name`、`action_id`、`score`、`should_execute`。

### 3.5 Retarget / IK / 控制层

当前主链路没有自研 retarget 或 IK。控制层是 Unitree 官方预置动作客户端：

- `llm_surf_context_node.py`
  - 方法：`_runner_command(action_id)` 生成 `[LLM_ACTION_RUNNER, "--network", UNITREE_NETWORK_INTERFACE, "--id", action_id]`。
  - 方法：`_execute_classified_action()` 调用 runner 并解析返回原因。
  - 方法：`release_arm()` 调用动作 ID `99` 释放手臂。

- `deps/unitree_g1_action_classifier_package/arm_action_classifier/arm_action_classifier.py`
  - 函数：`execute_action(result, network, runner)`
  - 调用 C++ runner，处理 `invalid_fsm_id`、`arm_holding_release_required`、`runner_reported_failure` 等情况。

- `deps/unitree_g1_action_classifier_package/unitree_sdk2/example/g1/high_level/g1_arm_action_example.cpp`
  - 使用 `ChannelFactory::Instance()->Init(0, network)` 初始化 DDS。
  - 使用 `G1ArmActionClient`。
  - `client->ExecuteAction(id)` 执行官方动作。

### 3.6 仿真层

当前仓库没有 Isaac Sim 或 MuJoCo 仿真入口，也没有发现仿真主流程。`deps/unitree_g1_action_classifier_package/unitree_sdk2/example/` 中有 Unitree SDK 示例代码，但主链路使用真实 Unitree DDS/AudioClient/G1ArmActionClient。

### 3.7 真机执行层

- 音频播放和灯光：
  - `unitree_audio_player.py`
  - `ChannelFactoryInitialize(CONFIG.unitree_domain_id, CONFIG.unitree_network_interface)`
  - `AudioClient().Init()`
  - `AudioClient.SetVolume()`
  - `_set_light()` 调用 `audio_client.LedControl(red, green, blue)`
  - `play_pcm_stream(audio_client, pcm_list, "tts")` 调用 `AudioClient.PlayStream()`

- 手臂动作：
  - `llm_surf_context_node.py` 调用 `LLM_ACTION_RUNNER`
  - runner 是 `deps/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example`
  - C++ 源码中 `G1ArmActionClient::ExecuteAction()` 连接 G1 官方动作服务。

### 3.8 配置层

- 根配置：`config/default.env`、`config/local.env.example`、`config/local.env`
- Python 配置对象：`project_config.py` 中 `ProjectConfig` 和全局 `CONFIG`
- SURF 子模块配置：`deps/SURF2026_VoiceModule-main/config/default.env`、`deps/SURF2026_VoiceModule-main/config/voice_config.py`
- RAG 配置：`xjtlu-rag-system/rag_config.py` 和 `xjtlu-rag-system/.env.example`
- 旧 Qwen 子包配置：`deps/qwen_ros_node_edg_tts/config/default.env`、`deps/qwen_ros_node_edg_tts/project_config.py`
- VSCode/CMake 辅助配置：`.vscode/settings.json`

### 3.9 日志与输出层

- systemd/journal：
  - `scripts/run_pipeline.sh` 使用 `systemd-run --user` 启动服务。
  - `scripts/tail_pipeline_logs.sh` 用 `journalctl --user` 查看服务日志。

- ROS 日志：
  - `scripts/run_surf_ros_bridge.sh` 和 `scripts/run_surf_context_node.sh` 设置 `ROS_LOG_DIR=runtime/ros_logs`。

- 会话日志：
  - `pipeline_log/pipeline_logger.py`
  - 类：`PipelineLogger`、`SessionLog`
  - 输出目录默认 `logs/`，可由 `PIPELINE_LOGS_DIR` 覆盖。
  - 每次唤醒创建 `logs/<timestamp>_sNNN/pipeline.log` 和 `audio.wav`。

- runtime 文件：
  - `runtime/status.json`：`llm_surf_context_node.py` 的 `_update_status()` 写入全链路状态。
  - `runtime/surf_context_status.json`：`_write_status()` 写入 SURF 上下文。
  - `runtime/tts.mp3`：`llm_server.py` 用 Edge TTS 生成。
  - `runtime/tts.wav`：`llm_surf_context_node.py` 用 ffmpeg 转换后供播放。
  - `runtime/tts_play_context.json`：描述当前播放类型、文本、session。
  - `runtime/wake_light_command.json`：灯光颜色命令。
  - `runtime/xjtlu_chat_memory.db`：RAG 对话记忆。

## 4. 端到端调用链

### 4.1 `./scripts/run_pipeline.sh --mode wake`

```text
scripts/run_pipeline.sh
  -> source config/default.env
  -> source /opt/ros/jazzy/setup.bash
  -> resolve_unitree_availability()
  -> systemd-run surf-ros-bridge
       -> scripts/run_surf_ros_bridge.sh
       -> surf_ros_bridge.py
       -> SurfRosBridge._poll()
  -> systemd-run surf-voice-runtime
       -> scripts/run_surf_voice_runtime.sh
       -> surf_voice_runtime.py
       -> SurfVoiceRuntime.start()
  -> if LLM_REPLY_BACKEND=rag:
       -> systemd-run surf-llm-ollama
          -> scripts/run_ollama_server.sh
          -> OLLAMA_BIN serve
       -> systemd-run surf-llm-rag
          -> scripts/run_rag_server.sh
          -> xjtlu-rag-system/app.py
  -> systemd-run surf-llm-server
       -> scripts/run_llm_server.sh
       -> uvicorn llm_server:app
  -> systemd-run surf-llm-node
       -> scripts/run_surf_context_node.sh
       -> llm_surf_context_node.py
       -> LlmSurfContextNode
  -> systemd-run surf-llm-audio-player
       -> scripts/run_audio_player.sh
       -> unitree_audio_player.py
```

### 4.2 语音到 ROS2 话题

```text
RobotMicCapture._recv_loop() or MicCapture._callback()
  -> AudioBus.push(pcm)
  -> VADEngine.process_frame()
  -> ChineseWakeWordDetector.push_audio() / WakeWordDetector.push_audio()
  -> ASREngine.push_audio()
  -> VoiceprintRecognizer.push_audio()

Wake detected:
  -> SurfVoiceRuntime._on_wake(word)
  -> PipelineLogger.start_session()
  -> ASREngine.start_recording()
  -> VoiceprintRecognizer.start_capture()
  -> UdpEventSink.publish("/wake_word_event", "string", json)
  -> SurfRosBridge._poll()
  -> ROS2 publish /wake_word_event

VAD change:
  -> SurfVoiceRuntime._on_vad(is_speech)
  -> UdpEventSink.publish("/vad_state", "bool", is_speech)
  -> ROS2 publish /vad_state

ASR complete:
  -> ASREngine.stop_and_transcribe()
  -> SurfVoiceRuntime._on_asr(text)
  -> UdpEventSink.publish("/audio_msg", "string", json)
  -> ROS2 publish /audio_msg

Speaker embedding:
  -> VoiceprintRecognizer
  -> SurfVoiceRuntime._on_embedding()
  -> SpeakerDatabase.identify_with_score()
  -> UdpEventSink.publish("/speaker_id", "string", json)
  -> ROS2 publish /speaker_id
```

### 4.3 LLM/RAG/TTS/动作链路

```text
LlmSurfContextNode.__init__()
  -> subscribe /audio_msg
  -> subscribe /wake_word_event
  -> subscribe /vad_state
  -> subscribe /speaker_id

/wake_word_event:
  -> LlmSurfContextNode.on_wake()
  -> _open_wake_listen_window()
  -> _maybe_play_wake_ack()
  -> _play_wake_ack()
  -> GET llm_server /tts
  -> _convert_tts_to_wav()
  -> _run_wake_ack_action()
  -> LLM_ACTION_RUNNER --id SURF_LLM_WAKE_ACK_ACTION_ID

/audio_msg:
  -> LlmSurfContextNode.on_audio_msg()
  -> _asr_ignore_reason()
  -> strip_wake_word() when LLM_ALWAYS_LISTEN=0
  -> _build_llm_text()
  -> _set_wake_light_green()
  -> _maybe_play_thinking_ack()
  -> _request_llm()
       -> GET llm_server.py /infer?text=...&session_id=...
       -> llm_server.infer()
          -> infer_rag() when LLM_REPLY_BACKEND=rag
             -> post_rag_chat()
             -> POST xjtlu-rag-system /chat
             -> chat_engine.chat()
                -> get_profile()/upsert_profile()/recent_messages()
                -> embed_text()
                -> vector_store.search()
                -> generate_text()
                -> return answer + action + sources + timing
          -> clean_text()
          -> detect_language()
          -> tts()
          -> write runtime/tts.mp3
       -> return reply/action/timing/lang/session_id
  -> _prepare_tts_wav()
       -> write runtime/tts_play_context.json
       -> GET llm_server.py /tts
       -> ffmpeg runtime/tts.mp3 -> runtime/tts.wav
  -> start thread run_reply_action()
       -> _classification_from_deepseek_action() if RAG action exists
       -> _execute_classified_action()
          -> LLM_ACTION_RUNNER --network UNITREE_NETWORK_INTERFACE --id action_id
       -> optional release_arm()
```

### 4.4 TTS 文件到 G1 扬声器/灯光

```text
unitree_audio_player.py
  -> ChannelFactoryInitialize(UNITREE_DOMAIN_ID, UNITREE_NETWORK_INTERFACE)
  -> AudioClient.Init()
  -> AudioClient.SetVolume(UNITREE_AUDIO_VOLUME)
  -> loop:
       if runtime/wake_light_command.json changed:
         -> _set_light()
         -> AudioClient.LedControl()
       if runtime/tts.wav changed:
         -> read_wav()
         -> play_pcm_stream()
         -> AudioClient.PlayStream()
```

## 5. 核心目录和文件

- `scripts/`
  - 启动、停止、检查、日志、打包脚本。
  - `run_pipeline.sh` 是主入口。

- `config/`
  - 集成工作区配置。
  - `default.env` 是默认配置；`local.env` 是本机覆盖和密钥；`local.env.example` 是模板。

- `project_config.py`
  - Python 侧统一读取 LLM、RAG、Unitree、动作和 runtime 路径。
  - 类：`ProjectConfig`
  - 全局：`CONFIG`

- `surf_voice_runtime.py`
  - 当前集成语音运行时。
  - 类：`SurfVoiceRuntime`、`UdpEventSink`

- `surf_ros_bridge.py`
  - UDP 到 ROS2 的轻量桥。
  - 类：`SurfRosBridge`

- `llm_surf_context_node.py`
  - 全链路核心编排 ROS2 节点。
  - 类：`LlmSurfContextNode`、`SurfContext`

- `llm_server.py`
  - FastAPI 服务，提供 `/health`、`/infer`、`/tts`。
  - 函数：`infer_local()`、`infer_dashscope()`、`infer_rag()`、`tts()`、`clean_text()`、`detect_language()`

- `unitree_audio_player.py`
  - 监听 runtime TTS/灯光文件，调用 Unitree G1 AudioClient 播放和控灯。

- `wav.py`
  - 函数：`read_wav()`、`write_wave()`、`play_pcm_stream()`
  - 用于解析 16-bit PCM WAV 并分块发送给 Unitree AudioClient。

- `pipeline_log/`
  - `pipeline_logger.py` 提供 session 日志。

- `xjtlu-rag-system/`
  - 独立 RAG 服务。
  - `app.py` 是 FastAPI 入口。
  - `chat_engine.py` 是检索、提示词、记忆、动作 JSON 生成核心。
  - `vector_store.py` 管理 SQLite 向量索引。
  - `memory_store.py` 管理用户画像和对话记忆。
  - `ollama_client.py` 调用 Ollama/OpenAI-compatible API。
  - `ingest.py` 构建向量索引。
  - `xjtlu_knowledge.db` 是源知识库。
  - `rag_index.db` 是向量索引库。

- `deps/SURF2026_VoiceModule-main/`
  - 外部 SURF 语音模块源码。
  - 当前集成通过 `surf_voice_runtime.py` 复用其中的 audio、wake、VAD、ASR、voice_id 组件。

- `deps/qwen_ros_node_edg_tts/`
  - 旧 Qwen ROS node + Unitree SDK Python vendored package。
  - 当前主要使用其 `third_party/unitree_sdk2_python/`。
  - `asr_dds_to_ros_bridge.py` 是可选 Unitree DDS ASR bridge。

- `deps/unitree_g1_action_classifier_package/`
  - 动作分类器和 Unitree C++ SDK。
  - `arm_action_classifier/arm_action_classifier.py` 是动作分类 CLI。
  - `unitree_sdk2/build/bin/g1_arm_action_example` 是真机动作 runner。

- `deps/Qwen3.5-0.8B/model/`
  - 本地 Qwen 模型权重和 tokenizer/config。
  - 仅 `LLM_REPLY_BACKEND=local` 时由 `llm_server.load_local_model()` 使用。

- `runtime/`
  - 当前运行产物。

- `logs/`
  - 每次唤醒/对话 session 的结构化日志和音频归档。

- `release-output/`
  - 打包产物，不属于主源码链路。

## 6. 配置文件清单

### 6.1 当前主链路配置

- `config/default.env`
  - 控制根路径：`WORKSPACE_ROOT`、`DEPS_ROOT`、`SURF_ROOT`、`LLM_ROOT`
  - 控制运行模式：`SURF_LLM_MODE`、`SURF_LLM_WAKE_WORDS`
  - 控制语音：`VOICE_AUDIO_SOURCE`、`SURF_LLM_ASR_WINDOW_SEC`、`SURF_LLM_VAD_HOLDOFF_SEC`、`VOICE_WAKE_WORD_LANG`
  - 控制 LLM：`LLM_AUDIO_TOPIC`、`LLM_SERVER_URL`、`LLM_WAKE_WORDS`、`LLM_MODEL_PATH`、`LLM_REPLY_BACKEND`
  - 控制服务：`LLM_SERVER_HOST`、`LLM_SERVER_PORT`、`LLM_RUNTIME_DIR`
  - 控制 Unitree：`UNITREE_DOMAIN_ID`、`UNITREE_ENABLE`、`UNITREE_NETWORK_INTERFACE`、`UNITREE_AUDIO_VOLUME`
  - 控制动作：`LLM_ACTION_ENABLE`、`LLM_ACTION_EXECUTE`、`LLM_ACTION_BACKEND`、`LLM_ACTION_THRESHOLD`、`LLM_ACTION_RUNNER`
  - 控制 SURF context：`SURF_WAKE_TOPIC`、`SURF_VAD_TOPIC`、`SURF_SPEAKER_TOPIC`
  - 控制 RAG：`RAG_SERVER_HOST`、`RAG_SERVER_PORT`、`SOURCE_DB`、`RAG_DB`、`MEMORY_DB`、`CHAT_PROVIDER`、`EMBED_PROVIDER`、`OLLAMA_BASE_URL`、`EMBED_MODEL`、`CHAT_MODEL`
  - 文件末尾加载 `config/local.env`

- `config/local.env.example`
  - 本机配置模板。
  - 覆盖 Python 解释器、Unitree 网口、机器人麦克风地址、DeepSeek/OpenAI-compatible API、Ollama、RAG、UX toggles。

- `config/local.env`
  - 本机真实覆盖文件，可能包含密钥，不应提交或复制到文档。

- `project_config.py`
  - 将环境变量转换为 Python `CONFIG` 对象。
  - 同时提供 runtime 派生路径：`tts_mp3_path`、`tts_wav_path`、`wake_light_command_path`、`tts_play_context_path`。

### 6.2 SURF 语音配置

- `deps/SURF2026_VoiceModule-main/config/default.env`
  - 音频帧参数：`VOICE_SAMPLE_RATE`、`VOICE_CHANNELS`、`VOICE_FRAME_MS`、`VOICE_BUS_BUFFER_SEC`
  - 输入源：`VOICE_AUDIO_SOURCE`
  - 机器人麦克风 UDP：`VOICE_ROBOT_MIC_GROUP`、`VOICE_ROBOT_MIC_PORT`、`VOICE_ROBOT_MIC_IF`
  - 唤醒词：`VOICE_WAKE_WORD_LANG`、`VOICE_KWS_MODEL_DIR`、`VOICE_WAKE_THRESHOLD`
  - VAD：`VOICE_VAD_SILENCE_FRAMES`、`VOICE_VAD_HOLDOFF_SEC`
  - ASR：`VOICE_ASR_MODEL`、`VOICE_ASR_VAD_MODEL`、`VOICE_ASR_WINDOW_SEC`
    - `VOICE_ASR_VAD_MODEL` 默认 `""`，避免 FunASR 初始化额外加载 `fsmn-vad`。
    - 实时端点检测由外层 WebRTC VAD `VADEngine` 负责；需要测试 FunASR 内置 VAD 时再显式设置 `VOICE_ASR_VAD_MODEL=fsmn-vad`。
  - 声纹：`VOICE_VOICEPRINT_MODEL`、`VOICE_VOICEPRINT_SEC`、`VOICE_SPEAKER_SIM_THRESHOLD`
  - ROS topics：`VOICE_ROS_AUDIO_TOPIC`、`VOICE_ROS_WAKE_TOPIC`、`VOICE_ROS_VAD_TOPIC`、`VOICE_ROS_SPEAKER_TOPIC`

- `deps/SURF2026_VoiceModule-main/config/voice_config.py`
  - Python 配置类 `VoiceConfig`，被 `surf_voice_runtime.py` 和 SURF 子模块类读取。

### 6.3 RAG 配置

- `xjtlu-rag-system/.env.example`
  - RAG 独立运行模板。
  - 控制 `SOURCE_DB`、`RAG_DB`、`MEMORY_DB`、`CHAT_PROVIDER`、`EMBED_PROVIDER`、`OLLAMA_BASE_URL`、`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`TOP_K`、`SIMILARITY_THRESHOLD`、ROS bridge topics。

- `xjtlu-rag-system/rag_config.py`
  - 函数 `_load_dotenv()` 会读取当前目录 `.env`。
  - 类 `Settings` 提供 `settings` 全局对象。

### 6.4 外部/旧子包配置

- `deps/qwen_ros_node_edg_tts/config/default.env`
  - 旧 Qwen ROS node 配置，当前主链路不直接 source，但保留为历史包配置。

- `deps/qwen_ros_node_edg_tts/project_config.py`
  - 旧子包 Python 配置对象。

- `.vscode/settings.json`
  - 指向 Unitree SDK state_machine 示例的 CMake source directory，仅开发辅助。

- `deps/unitree_g1_action_classifier_package/unitree_sdk2/CMakeLists.txt` 和 `example/*/CMakeLists.txt`
  - Unitree C++ SDK 编译配置。

## 7. 外部依赖和环境变量

### 7.1 Python 依赖

- `requirements-llm.txt`
  - FastAPI/Uvicorn/httpx/pydantic/numpy
  - edge-tts、requests、certifi
  - transformers、accelerate、torch
  - opencv-python
  - editable 安装 `deps/qwen_ros_node_edg_tts/third_party/unitree_sdk2_python`

- `requirements-voice.txt`
  - numpy/scipy
  - openwakeword、webrtcvad-wheels、PyAudio、sounddevice、soundfile
  - funasr、modelscope、onnxruntime、sherpa-onnx
  - torch、pyannote.audio、librosa

- `xjtlu-rag-system/requirements.txt`
  - 当前文件通过 `-r ../requirements-llm.txt` 复用主 LLM 环境依赖。

- `deps/unitree_g1_action_classifier_package/requirements.txt`
  - 动作分类器独立环境依赖。

### 7.2 系统依赖

- ROS2 Jazzy：脚本 source `/opt/ros/jazzy/setup.bash`，运行 `rclpy` 和 `std_msgs`。
- ffmpeg：`llm_surf_context_node.py` 的 `_convert_tts_to_wav()` 使用。
- systemd user：`scripts/run_pipeline.sh` 使用 `systemd-run --user`。
- curl：健康检查。
- iproute2：`ip -o link show` 检查 Unitree 网口。
- Ollama：`OLLAMA_BIN serve`，embedding 模型默认 `nomic-embed-text`。
- Unitree SDK2/CycloneDDS：Python SDK 和 C++ SDK 均在 `deps/` 下。

### 7.3 关键环境变量

- Python 环境：
  - `LLM_PYTHON`
  - `VOICE_PYTHON`
  - `LLM_ACTION_PYTHON`

- ROS/桥接：
  - `LLM_AUDIO_TOPIC`
  - `SURF_WAKE_TOPIC`
  - `SURF_VAD_TOPIC`
  - `SURF_SPEAKER_TOPIC`
  - `SURF_BRIDGE_HOST`
  - `SURF_BRIDGE_PORT`
  - `ROS_LOG_DIR`

- 语音：
  - `VOICE_AUDIO_SOURCE`
  - `VOICE_ROBOT_MIC_GROUP`
  - `VOICE_ROBOT_MIC_PORT`
  - `VOICE_ROBOT_MIC_IF`
  - `VOICE_ASR_MODEL`
  - `VOICE_KWS_MODEL_DIR`
  - `VOICE_VOICEPRINT_MODEL`
  - `VOICE_KEEP_ASR_DEADLINE`

- LLM/RAG：
  - `LLM_REPLY_BACKEND`
  - `LLM_SERVER_URL`
  - `LLM_MODEL_PATH`
  - `LLM_RAG_SERVER_URL`
  - `SOURCE_DB`
  - `RAG_DB`
  - `MEMORY_DB`
  - `CHAT_PROVIDER`
  - `CHAT_MODEL`
  - `OPENAI_BASE_URL`
  - `OPENAI_API_KEY`
  - `EMBED_PROVIDER`
  - `EMBED_MODEL`
  - `OLLAMA_BASE_URL`
  - `OLLAMA_BIN`
  - `OLLAMA_HOME`
  - `OLLAMA_MODELS`

- Unitree：
  - `UNITREE_ENABLE`
  - `UNITREE_DOMAIN_ID`
  - `UNITREE_NETWORK_INTERFACE`
  - `UNITREE_AUDIO_VOLUME`
  - `LD_LIBRARY_PATH`，由 `llm_surf_context_node.py::action_env()` 和 `arm_action_classifier.py::build_runner_env()` 动态补充。

- 动作：
  - `LLM_ACTION_ENABLE`
  - `LLM_ACTION_EXECUTE`
  - `LLM_ACTION_BACKEND`
  - `LLM_ACTION_THRESHOLD`
  - `LLM_ACTION_RUNNER`
  - `LLM_ACTION_AUTO_RELEASE`
  - `LLM_ACTION_RELEASE_AFTER_SEC`
  - `LLM_ACTION_KEYWORD_FIRST`

## 8. 模型、数据库和外部资源路径

- 本地 Qwen 模型：
  - `deps/Qwen3.5-0.8B/model/`
  - 关键文件：`model.safetensors-00001-of-00001.safetensors`、`model.safetensors.index.json`、`config.json`、`tokenizer.json`
  - 使用点：`llm_server.py::load_local_model()`

- SURF 中文唤醒模型：
  - `deps/SURF2026_VoiceModule-main/models/kws/*.onnx`
  - 使用点：`ChineseWakeWordDetector`

- SURF ASR 模型：
  - 默认路径：`${HOME}/.cache/modelscope/hub/models/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`
  - bundle 中也出现：`release-output/surf_llm_bundle/cache/modelscope/...`
  - 使用点：`ASREngine`

- 声纹模型：
  - 默认 id：`pyannote/wespeaker-voxceleb-resnet34-LM`
  - cache 位置由 `HF_HOME`、`HF_HUB_CACHE` 控制。

- XJTLU 源知识库：
  - `xjtlu-rag-system/xjtlu_knowledge.db`
  - 表读取点：`knowledge_extract.py::extract_items()`、`chat_engine.py` 的 direct FAQ/programme/school overview 查询。

- XJTLU 向量索引：
  - `xjtlu-rag-system/rag_index.db`
  - 表：`chunks`
  - 使用点：`vector_store.py`

- RAG 对话记忆：
  - `runtime/xjtlu_chat_memory.db`
  - 表：`user_profile`、`messages`
  - 使用点：`memory_store.py`

- Unitree Python SDK：
  - `deps/qwen_ros_node_edg_tts/third_party/unitree_sdk2_python/`
  - 使用点：`unitree_audio_player.py`、`asr_dds_to_ros_bridge.py`

- Unitree C++ SDK 和 runner：
  - SDK：`deps/unitree_g1_action_classifier_package/unitree_sdk2/`
  - runner：`deps/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example`
  - 动态库：`deps/unitree_g1_action_classifier_package/unitree_sdk2/thirdparty/lib/<arch>/`

- Ollama：
  - binary：`deps/ollama/bin/ollama`
  - home/cache：`deps/ollama-home/`
  - 模型目录：`${OLLAMA_HOME}/models`

## 9. 动作白名单

当前动作白名单在两处维护：

- `xjtlu-rag-system/chat_engine.py::ACTIONS`
- `llm_surf_context_node.py::_classification_from_deepseek_action()`
- `deps/unitree_g1_action_classifier_package/arm_action_classifier/arm_action_classifier.py::ACTIONS`

主要映射：

| label | official_name | action_id |
| --- | --- | --- |
| 无动作 | none | -1 |
| 释放手臂 | release arm | 99 |
| 双手飞吻 | two-hand kiss | 11 |
| 右手飞吻 | right kiss | 13 |
| 左手飞吻 | left kiss | 12 |
| 举双手 | hands up | 15 |
| 鼓掌 | clap | 17 |
| 击掌 | high five | 18 |
| 拥抱 | hug | 19 |
| 比心 | heart | 20 |
| 右手比心 | right heart | 21 |
| 拒绝摆手 | reject | 22 |
| 举右手 | right hand up | 23 |
| x-ray | x-ray | 24 |
| 面前挥手 | face wave | 25 |
| 高位挥手 | high wave | 26 |
| 握手 | shake hand | 27 |

## 10. 当前主链路和旧链路的区别

当前主链路：

```text
surf_voice_runtime.py
-> UDP event
-> surf_ros_bridge.py
-> ROS2 topics
-> llm_surf_context_node.py
```

旧/备用链路：

```text
deps/SURF2026_VoiceModule-main/ros_nodes/voice_pipeline_node.py
-> 直接发布 ROS2 topics
```

另一个备用链路：

```text
deps/qwen_ros_node_edg_tts/asr_dds_to_ros_bridge.py
-> Unitree DDS rt/audio_msg
-> ROS2 /audio_msg
```

`scripts/run_pipeline.sh` 明确设置 `LLM_AUTOSTART_ASR_BRIDGE=0`，并打印 “LLM DDS ASR bridge: disabled”，因此当前 ASR 来源是 SURF 语音运行时。

## 11. 风险点和维护注意事项

- 动作白名单在 RAG、context node、动作分类器三处重复维护，新增动作时要同步。
- `config/local.env` 是本机真实配置和密钥覆盖文件，不应提交或在文档中展开。
- `UNITREE_NETWORK_INTERFACE` 不在线时，`scripts/run_pipeline.sh` 会自动设置 `UNITREE_ENABLE=0` 和 `LLM_ACTION_EXECUTE=0`，主语音/RAG链路仍可启动，但不会真机播放/动作。
- `unitree_audio_player.py` 通过文件 mtime 监听 `runtime/tts.wav`，TTS 覆盖写入顺序会影响播放。
- `llm_surf_context_node.py` 使用 `_tts_lock` 串行化 wake ack、thinking ack 和 reply TTS，但 `unitree_audio_player.py` 仍是文件级消费。
- `llm_server.py` 的本地模型路径只在 `LLM_REPLY_BACKEND=local` 时使用；默认 `rag` 走 `xjtlu-rag-system`。
- RAG 的 `chat_engine.py` 会要求 DeepSeek/OpenAI-compatible 输出严格 JSON；若模型返回非 JSON，会由 `_parse_json_object()` 尝试提取对象。
