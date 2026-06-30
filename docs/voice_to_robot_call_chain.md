# Voice to Robot Call Chain

本文按“用户说话 -> 机器人回应”的单条运行链路追踪当前集成实现。主启动入口是 `scripts/run_pipeline.sh --mode wake|listen`，配置入口是 `config/default.env`，本机覆盖来自 `config/local.env`。

## 0. 总览

```text
用户语音
-> RobotMicCapture / MicCapture
-> AudioBus
-> SurfVoiceRuntime
-> UdpEventSink
-> SurfRosBridge
-> ROS2 topics
-> LlmSurfContextNode
-> llm_server.py /infer
-> RAG app.py /chat 或 DashScope/local Qwen
-> llm_server.py /tts + Edge TTS
-> llm_surf_context_node.py ffmpeg 转 wav
-> runtime/tts.wav
-> unitree_audio_player.py
-> Unitree G1 AudioClient.PlayStream()
```

同一条链路上，灯光和手臂动作由 `llm_surf_context_node.py` 触发：

- 灯光：写 `runtime/wake_light_command.json`，由 `unitree_audio_player.py` 读文件并调用 `AudioClient.LedControl()`。
- 手臂动作：调用 `LLM_ACTION_RUNNER`，默认是 `deps/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example`。

## 1. 用户语音从哪里进入？

### 文件和类

- `surf_voice_runtime.py`
  - `SurfVoiceRuntime.__init__()`
- `deps/SURF2026_VoiceModule-main/audio/robot_mic_capture.py`
  - `RobotMicCapture`
  - `RobotMicCapture.start()`
  - `RobotMicCapture._recv_loop()`
- `deps/SURF2026_VoiceModule-main/audio/mic_capture.py`
  - `MicCapture`
- `deps/SURF2026_VoiceModule-main/audio/audio_bus.py`
  - `AudioBus`
  - `AudioBus.push()`
  - `AudioBus.register()`
  - `AudioBus.get_buffer()`

### Input

- 用户语音，最终变成 16 kHz、16-bit、mono PCM 帧。
- 默认输入源是机器人麦克风 UDP 组播。
- 相关配置：
  - `config/default.env`
    - `VOICE_AUDIO_SOURCE="${VOICE_AUDIO_SOURCE:-robot}"`
  - `deps/SURF2026_VoiceModule-main/config/default.env`
    - `VOICE_ROBOT_MIC_GROUP`
    - `VOICE_ROBOT_MIC_PORT`
    - `VOICE_ROBOT_MIC_IF`
    - `VOICE_SAMPLE_RATE`
    - `VOICE_CHANNELS`
    - `VOICE_FRAME_MS`
  - `deps/SURF2026_VoiceModule-main/config/voice_config.py`
    - `VoiceConfig.audio_source`
    - `VoiceConfig.robot_mic_group`
    - `VoiceConfig.robot_mic_port`
    - `VoiceConfig.robot_mic_interface`
    - `VoiceConfig.frame_bytes`

### Process

`SurfVoiceRuntime.__init__()` 根据 `CONFIG.audio_source` 选择输入实现：

```text
CONFIG.audio_source == "robot" -> RobotMicCapture(bus=self._bus)
else -> MicCapture(bus=self._bus)
```

`RobotMicCapture.start()` 创建 UDP socket，加入 `VOICE_ROBOT_MIC_GROUP`，在 `VOICE_ROBOT_MIC_IF` 上接收 `VOICE_ROBOT_MIC_PORT` 的音频包。

`RobotMicCapture._recv_loop()` 把 UDP 数据累计到 `_pending`，每满 `CONFIG.frame_bytes` 就切出一帧，调用：

```text
AudioBus.push(frame)
```

`AudioBus.push()` 会把同一帧广播给所有已注册 consumer，并保存到 rolling buffer，供唤醒时回溯。

### Output

- 输出给 `AudioBus` 的 PCM frame。
- 下游 consumer 在 `SurfVoiceRuntime.__init__()` 注册：
  - `VADEngine.process_frame`
  - `ChineseWakeWordDetector.push_audio` 或 `WakeWordDetector.push_audio`
  - `ASREngine.push_audio`
  - `VoiceprintRecognizer.push_audio`
  - `SurfVoiceRuntime._collect_audio`

## 2. SURF voice runtime 做了什么？

### 文件和类

- `surf_voice_runtime.py`
  - `SurfVoiceRuntime`
  - `SurfVoiceRuntime.start()`
  - `SurfVoiceRuntime.spin()`
  - `SurfVoiceRuntime._on_wake()`
  - `SurfVoiceRuntime._on_vad()`
  - `SurfVoiceRuntime._on_asr()`
  - `SurfVoiceRuntime._on_embedding()`
  - `SurfVoiceRuntime._cancel_asr_deadline()`
  - `SurfVoiceRuntime._save_audio()`
  - `UdpEventSink.publish()`
- SURF 子模块：
  - `deps/SURF2026_VoiceModule-main/asr/asr_engine.py::ASREngine`
  - `deps/SURF2026_VoiceModule-main/vad/vad_engine.py::VADEngine`
  - `deps/SURF2026_VoiceModule-main/wake_word/chinese_wake_word_detector.py::ChineseWakeWordDetector`
  - `deps/SURF2026_VoiceModule-main/wake_word/wake_word_detector.py::WakeWordDetector`
  - `deps/SURF2026_VoiceModule-main/wake_word/wakeup_dispatcher.py::WakeupDispatcher`
  - `deps/SURF2026_VoiceModule-main/voice_id/voiceprint_recognizer.py::VoiceprintRecognizer`
  - `deps/SURF2026_VoiceModule-main/voice_id/speaker_database.py::SpeakerDatabase`
- `pipeline_log/pipeline_logger.py`
  - `PipelineLogger`
  - `SessionLog`

### Input

- 来自 `AudioBus.push()` 的 PCM frame。
- 唤醒词模型、ASR 模型、VAD 参数、声纹模型由 SURF 配置控制：
  - `VOICE_WAKE_WORD_LANG`
  - `VOICE_KWS_MODEL_DIR`
  - `VOICE_WAKE_THRESHOLD`
  - `VOICE_ASR_MODEL`
  - `VOICE_ASR_VAD_MODEL`，默认 `""`，FunASR 内置 fsmn-vad 默认关闭
  - `VOICE_ASR_WINDOW_SEC`
  - `VOICE_VAD_HOLDOFF_SEC`
  - `VOICE_KEEP_ASR_DEADLINE`
  - `VOICE_VOICEPRINT_MODEL`

### Process

端点检测默认由外层 `deps/SURF2026_VoiceModule-main/vad/vad_engine.py::VADEngine` 的 WebRTC VAD 完成。`deps/SURF2026_VoiceModule-main/asr/asr_engine.py::ASREngine.__init__()` 只有在 `CONFIG.asr_vad_model` 非空时才向 FunASR `AutoModel` 传入 `vad_model`，因此默认不会加载 `fsmn-vad`。

`SurfVoiceRuntime.start()` 启动 wake word detector 和 mic capture。

`SurfVoiceRuntime.__init__()` 组装语音流水线：

```text
AudioBus
  -> VADEngine.process_frame
  -> WakeWordDetector / ChineseWakeWordDetector
  -> ASREngine
  -> VoiceprintRecognizer
  -> _collect_audio
```

唤醒回调 `SurfVoiceRuntime._on_wake(word)`：

1. 调用 `_new_session()`，内部使用 `PipelineLogger.start_session()` 创建 session。
2. 通过 `UdpEventSink.publish()` 发送 `/wake_word_event`。
3. 从 `AudioBus.get_buffer()` 取最近音频，作为 ASR initial audio。
4. 调用 `ASREngine.start_recording()`。
5. 调用 `VoiceprintRecognizer.start_capture()`。
6. 设置 ASR deadline 和 VAD holdoff。

VAD 回调 `SurfVoiceRuntime._on_vad(is_speech)`：

1. 发送 `/vad_state`。
2. 如果检测到 speech，调用 `_cancel_asr_deadline("vad_speech")`。
3. 如果静音并超过 holdoff，停止录音，保存音频，然后调用 `ASREngine.stop_and_transcribe()`。

ASR 回调 `SurfVoiceRuntime._on_asr(text)`：

1. 组装 JSON：

```json
{
  "text": "...",
  "speaker": "...",
  "session_id": "...",
  "time": 0
}
```

2. 通过 `UdpEventSink.publish("/audio_msg", "string", json_string)` 发出。
3. 使用 `SessionLog.record_duration("asr_result", ...)` 记录日志。

声纹回调 `SurfVoiceRuntime._on_embedding(embedding)`：

1. 调用 `SpeakerDatabase.identify_with_score()`。
2. 发送 `/speaker_id`，payload 包含 `speaker` 和 `score`。

`SurfVoiceRuntime.spin()` 持续检查 `_asr_deadline`。如果超时，强制调用 `ASREngine.stop_and_transcribe()`。

### Output

`SurfVoiceRuntime` 不直接发布 ROS2 topic。它输出 UDP JSON 事件给 `surf_ros_bridge.py`：

- topic `/wake_word_event`，type `string`
- topic `/vad_state`，type `bool`
- topic `/speaker_id`，type `string`
- topic `/audio_msg`，type `string`

UDP 目标由环境变量控制：

- `SURF_BRIDGE_HOST`，默认 `127.0.0.1`
- `SURF_BRIDGE_PORT`，默认 `18765`

## 3. `surf_ros_bridge.py` 怎么把语音结果转成 ROS2 topic？

### 文件和类

- `surf_ros_bridge.py`
  - `SurfRosBridge`
  - `SurfRosBridge.__init__()`
  - `SurfRosBridge._poll()`
  - `main()`

### Input

来自 `UdpEventSink.publish()` 的 UDP JSON：

```json
{
  "topic": "/audio_msg",
  "type": "string",
  "data": "{\"text\":\"...\",\"speaker\":\"...\",\"session_id\":\"...\"}",
  "time": 0
}
```

或：

```json
{
  "topic": "/vad_state",
  "type": "bool",
  "data": true,
  "time": 0
}
```

配置：

- `SURF_BRIDGE_HOST`
- `SURF_BRIDGE_PORT`
- `scripts/run_surf_ros_bridge.sh` 设置：
  - `ROS_LOG_DIR="${WORKSPACE_ROOT}/runtime/ros_logs"`
  - `PYTHONPATH="${WORKSPACE_ROOT}:${PYTHONPATH:-}"`
  - source `/opt/ros/jazzy/setup.bash`

### Process

`SurfRosBridge.__init__()`：

1. 创建 ROS2 node，名称是 `surf_udp_ros_bridge`。
2. 绑定 UDP socket 到 `SURF_BRIDGE_HOST:SURF_BRIDGE_PORT`。
3. 创建 `create_timer(0.02, self._poll)`，每 20 ms poll 一次 UDP socket。

`SurfRosBridge._poll()`：

1. `recvfrom()` 读取 UDP bytes。
2. `json.loads()` 解析 event。
3. 读取：
   - `topic`
   - `type`
   - `data`
4. 如果 `type == "bool"`：
   - 动态创建或复用 `std_msgs.msg.Bool` publisher。
   - `pub.publish(Bool(data=bool(data)))`
5. 否则：
   - 动态创建或复用 `std_msgs.msg.String` publisher。
   - `pub.publish(String(data=str(data)))`

### Output

ROS2 topics：

- `/wake_word_event`，`std_msgs/msg/String`
- `/vad_state`，`std_msgs/msg/Bool`
- `/speaker_id`，`std_msgs/msg/String`
- `/audio_msg`，`std_msgs/msg/String`

其中 `/audio_msg` 的 `String.data` 通常是 JSON 字符串，包含 `text`、`speaker`、`session_id`、`time`。

## 4. `llm_surf_context_node.py` 订阅了哪些 topic？

### 文件和类

- `llm_surf_context_node.py`
  - `LlmSurfContextNode`
  - `SurfContext`
  - `LlmSurfContextNode.__init__()`
  - `LlmSurfContextNode.on_wake()`
  - `LlmSurfContextNode.on_vad()`
  - `LlmSurfContextNode.on_speaker()`
  - `LlmSurfContextNode.on_audio_msg()`

### Input

`LlmSurfContextNode.__init__()` 创建四个 subscription：

```text
CONFIG.ros_audio_topic   -> on_audio_msg()
CONFIG.surf_wake_topic   -> on_wake()
CONFIG.surf_vad_topic    -> on_vad()
CONFIG.surf_speaker_topic -> on_speaker()
```

默认 topic 来自 `config/default.env` 和 `project_config.py`：

- `LLM_AUDIO_TOPIC=/audio_msg`
- `SURF_WAKE_TOPIC=/wake_word_event`
- `SURF_VAD_TOPIC=/vad_state`
- `SURF_SPEAKER_TOPIC=/speaker_id`

消息类型：

- `/audio_msg`：`std_msgs/msg/String`
- `/wake_word_event`：`std_msgs/msg/String`
- `/vad_state`：`std_msgs/msg/Bool`
- `/speaker_id`：`std_msgs/msg/String`

### Process

`on_wake(msg)`：

1. 用 `_decode_json_payload()` 解析 wake payload。
2. 更新 `SurfContext.wake_word` 和 `SurfContext.wake_time`。
3. 调用 `_attach_session(session_id)` 绑定 session log。
4. 调用 `_open_wake_listen_window()` 打开等待命令状态。
5. 调用 `_maybe_play_wake_ack()` 触发唤醒确认 TTS 和可选动作。

`on_vad(msg)`：

1. 更新 `SurfContext.vad_is_speech` 和 `SurfContext.vad_time`。
2. 如果是 speech，调用 `_mark_wake_command_started()`。
3. 写 `runtime/surf_context_status.json`。

`on_speaker(msg)`：

1. 解析 `speaker` 和 `score`。
2. 更新 `SurfContext.speaker`、`speaker_score`、`speaker_time`。
3. 写 `runtime/status.json` 和 `runtime/surf_context_status.json`。

`on_audio_msg(msg)`：

1. 解析 ASR JSON，提取：
   - `text`
   - `speaker`
   - `session_id`
   - `confidence`
2. 调用 `_asr_ignore_reason()` 过滤空文本、低置信度、太短、纯标点、英文 filler。
3. 如果不是 `LLM_ALWAYS_LISTEN`，调用 `strip_wake_word()` 做第二层唤醒词过滤。
4. 调用 `_build_llm_text()` 构造发给 LLM server 的文本。
5. 调用 `_request_llm()` 请求 HTTP API。
6. 调用 `_prepare_tts_wav()` 准备可播放 WAV。
7. 起线程调用 `run_reply_action()` 处理动作。

### Output

- HTTP 请求到 LLM server。
- runtime 文件：
  - `runtime/status.json`
  - `runtime/surf_context_status.json`
  - `runtime/wake_light_command.json`
  - `runtime/tts_play_context.json`
  - `runtime/tts.wav`
- 可选真机动作 subprocess。

## 5. 它如何组织 prompt / context / history？

这里有两层组织：

1. `llm_surf_context_node.py` 组织 SURF context 和发给 LLM server 的 `text/session_id`。
2. `xjtlu-rag-system/chat_engine.py` 在 RAG backend 下组织最终 prompt、knowledge context、history、profile 和 action schema。

### 5.1 `llm_surf_context_node.py` 的上下文组织

#### 文件和函数

- `llm_surf_context_node.py`
  - `SurfContext`
  - `LlmSurfContextNode._build_llm_text()`
  - `LlmSurfContextNode._fallback_session_id()`
  - `LlmSurfContextNode._attach_session()`
  - `LlmSurfContextNode._session_record()`

#### Input

- ASR text：来自 `/audio_msg`
- speaker：来自 `/speaker_id` 或 `/audio_msg` payload
- wake metadata：来自 `/wake_word_event`
- 配置：
  - `LLM_REPLY_BACKEND`
  - `SURF_LLM_INCLUDE_SPEAKER_CONTEXT`
  - `LLM_ALWAYS_LISTEN`
  - `LLM_WAKE_WORDS`

#### Process

`_build_llm_text(user_text)`：

- 如果 `CONFIG.reply_backend == "rag"`，直接返回 `user_text`。
- 如果不是 RAG，且 `SURF_LLM_INCLUDE_SPEAKER_CONTEXT=1` 且已有 speaker，则拼接：

```text
系统上下文：当前说话人是{speaker}。除非用户询问身份或上下文，否则不要在回复中复述这句系统上下文。
用户说：{user_text}
```

`_fallback_session_id()`：

- 如果没有 `/audio_msg` 的 `session_id`，使用 speaker 派生 session id。

#### Output

传给 LLM server 的 HTTP 参数：

```text
GET CONFIG.llm_server_url?text={llm_text}&session_id={request_session_id}
```

默认：

```text
GET http://127.0.0.1:8000/infer?text=...&session_id=...
```

### 5.2 RAG backend 的 prompt/context/history 组织

#### 文件和函数

- `xjtlu-rag-system/chat_engine.py`
  - `chat(session_id, message)`
  - `_infer_identity()`
  - `_extract_profile_updates()`
  - `_needs_rag()`
  - `_format_history()`
  - `_format_context()`
  - `_build_direct_faq_context()`
  - `_build_programme_context()`
  - `_build_school_overview_context()`
- `xjtlu-rag-system/memory_store.py`
  - `get_profile()`
  - `upsert_profile()`
  - `add_message()`
  - `recent_messages()`

#### Input

来自 `llm_server.py::post_rag_chat()` 的 JSON：

```json
{
  "message": "...",
  "session_id": "..."
}
```

RAG 配置来自 `xjtlu-rag-system/rag_config.py::Settings`，默认由 `config/default.env` 注入：

- `SOURCE_DB`
- `RAG_DB`
- `MEMORY_DB`
- `CHAT_PROVIDER`
- `CHAT_MODEL`
- `EMBED_PROVIDER`
- `EMBED_MODEL`
- `TOP_K`
- `SIMILARITY_THRESHOLD`
- `ANSWER_MAX_CHARS`

#### Process

`chat(session_id, message)`：

1. 调用 `get_profile(settings.memory_db, session_id)` 读取用户画像。
2. 调用 `_infer_identity()` 判断助手身份：`招生顾问`、`学术导师`、`校园助手`。
3. 调用 `_extract_profile_updates()` 从用户文本抽取姓名、关注专业、语言偏好。
4. 调用 `upsert_profile()` 写画像。
5. 调用 `add_message(..., "user", message)` 写当前用户消息。
6. 调用 `recent_messages(limit=8)` 取最近对话 history。
7. 如果 `_needs_rag(message)` 为真：
   - 调用 `embed_text(message)` 生成 query embedding。
   - 调用 `vector_store.search(settings.rag_db, query_embedding, top_k, threshold)` 检索向量库。
8. 同时构造直接数据库补充：
   - `_build_direct_faq_context(message, settings.source_db)`
   - `_build_programme_context(message, settings.source_db)`
   - `_build_school_overview_context(message, settings.source_db)`
9. 构造 `system` prompt：
   - 规定助手身份。
   - 要求中文回答、短回答、不可编造高风险信息。
   - 要求同时输出动作白名单中的动作。
   - 要求严格 JSON。
10. 构造 `prompt`：
   - `用户画像`
   - `最近对话`
   - `知识库上下文`
   - `学校概况补充`
   - `FAQ精准补充`
   - `专业数据库补充`
   - `用户当前问题`
   - `动作白名单`
   - JSON schema
11. 调用 `generate_text(prompt, system)`。
12. 调用 `_parse_json_object()` 解析模型输出。
13. 调用 `_limit_answer()` 限制回答长度。
14. 调用 `_normalize_action()` 规范动作。
15. 调用 `add_message(..., "assistant", answer)` 写 assistant history。

#### Output

RAG `/chat` 返回：

```json
{
  "answer": "...",
  "action": {
    "label": "...",
    "official_name": "...",
    "action_id": 25,
    "score": 0.9,
    "backend": "deepseek",
    "reason": "..."
  },
  "identity": "...",
  "profile": {},
  "sources": [],
  "timing": {
    "rag_embed_sec": 0.0,
    "rag_search_sec": 0.0,
    "llm_sec": 0.0,
    "total_sec": 0.0
  }
}
```

## 6. 它如何调用 `llm_server.py`？

### 文件和函数

- `llm_surf_context_node.py`
  - `LlmSurfContextNode._request_llm()`
  - `LlmSurfContextNode._llm_tts_url()`
  - `LlmSurfContextNode._request_tts_mp3()`
  - `LlmSurfContextNode._prepare_tts_wav()`
- `project_config.py`
  - `ProjectConfig.llm_server_url`
  - `ProjectConfig.request_timeout_sec`

### Input

- `text`：由 `_build_llm_text()` 输出。
- `session_id`：来自 `/audio_msg` payload 或 `_fallback_session_id()`。
- 配置：
  - `LLM_SERVER_URL`，默认 `http://127.0.0.1:8000/infer`
  - `LLM_REQUEST_TIMEOUT_SEC`

### Process

`_request_llm(text, session_id)` 使用 `requests.Session`：

```text
HTTP GET CONFIG.llm_server_url
params:
  text={text}
  session_id={session_id}
timeout=CONFIG.request_timeout_sec
```

默认 API：

```text
GET http://127.0.0.1:8000/infer?text=...&session_id=...
```

收到响应后：

1. `response.raise_for_status()`
2. `response.json()`
3. 读取 `reply`
4. 返回完整 result 给 `on_audio_msg()`

TTS 另有 API：

```text
GET http://127.0.0.1:8000/tts?text=...
```

`_llm_tts_url()` 通过把 `/infer` 替换成 `/tts` 得出。

### Output

`_request_llm()` 期望 `llm_server.py::infer()` 返回：

```json
{
  "reply": "...",
  "action": {},
  "timing": {},
  "lang": "zh",
  "session_id": "..."
}
```

随后 `on_audio_msg()` 会：

- 更新 `runtime/status.json`
- 调用 `_prepare_tts_wav("reply", reply, session_id=...)`
- 启动 `run_reply_action()` 线程处理动作。

## 7. `llm_server.py` 如何选择 backend：RAG / DeepSeek / Qwen？

### 文件和函数

- `llm_server.py`
  - FastAPI app：`app`
  - `health()`
  - `infer(text, session_id)`
  - `infer_rag()`
  - `post_rag_chat()`
  - `infer_dashscope()`
  - `post_chat_completion()`
  - `infer_local()`
  - `load_local_model()`
  - `build_prompt()`
  - `clean_text()`
  - `detect_language()`
  - `tts()`
- `project_config.py`
  - `ProjectConfig.reply_backend`
  - `ProjectConfig.rag_server_url`
  - `ProjectConfig.dashscope_model`
  - `ProjectConfig.model_path`

### Input

HTTP:

```text
GET /infer?text=...&session_id=...
```

配置：

- `LLM_REPLY_BACKEND`
  - `rag`
  - `dashscope`
  - `local`
- `LLM_RAG_SERVER_URL`
- `LLM_DASHSCOPE_MODEL`
- `LLM_DASHSCOPE_BASE_URL`
- `DASHSCOPE_API_KEY`
- `LLM_MODEL_PATH`
- `LLM_MAX_NEW_TOKENS`
- `LLM_TEMPERATURE`

### Process

`llm_server.py::infer(text, session_id)`：

1. `detect_language(text)` 判断用户语言。
2. 根据 `CONFIG.reply_backend` 分支：

#### `LLM_REPLY_BACKEND=rag`

```text
infer()
-> infer_rag(text, session_id)
-> post_rag_chat(text, session_id)
-> POST CONFIG.rag_server_url
```

默认：

```text
POST http://127.0.0.1:8010/chat
Content-Type: application/json
{
  "message": "...",
  "session_id": "..."
}
```

RAG 内部的 LLM 默认是 DeepSeek/OpenAI-compatible：

- `CHAT_PROVIDER=openai`
- `CHAT_MODEL=deepseek-v4-pro`
- `OPENAI_BASE_URL=https://api.deepseek.com`

#### `LLM_REPLY_BACKEND=dashscope`

```text
infer()
-> infer_dashscope(text, user_lang)
-> post_chat_completion(payload)
```

`infer_dashscope()` 用 `build_prompt(user_lang)` 构造 system prompt，调用 DashScope OpenAI-compatible `/chat/completions`。

#### `LLM_REPLY_BACKEND=local`

```text
infer()
-> infer_local(text, user_lang)
-> load_local_model()
-> AutoProcessor.from_pretrained(CONFIG.model_path)
-> AutoModelForImageTextToText.from_pretrained(CONFIG.model_path)
```

本地模型路径默认：

```text
deps/Qwen3.5-0.8B/model
```

3. 统一调用 `clean_text(reply)` 清理 `<think>`、Markdown、emoji 和 TTS 不适合的符号。
4. 调用 `detect_language(reply, preferred_lang=user_lang)` 判断 TTS 语言。
5. 调用 `await tts(reply, lang)` 生成 `runtime/tts.mp3`。

### Output

HTTP JSON：

```json
{
  "reply": "...",
  "action": {},
  "timing": {},
  "lang": "zh",
  "session_id": "..."
}
```

副作用：

- 写 `runtime/tts.mp3`

注意：在主链路中，`llm_surf_context_node.py` 收到 `/infer` 响应后仍会再次调用 `/tts`，然后用 ffmpeg 生成 `runtime/tts.wav`，供 G1 播放。

## 8. RAG 系统 `app.py` 如何检索知识库？

### 文件和函数

- `xjtlu-rag-system/app.py`
  - `ChatRequest`
  - `lifespan()`
  - `chat_api()`
  - `health()`
- `xjtlu-rag-system/rag_config.py`
  - `Settings`
  - `settings`
- `xjtlu-rag-system/chat_engine.py`
  - `chat()`
  - `_needs_rag()`
  - `_build_direct_faq_context()`
  - `_build_programme_context()`
  - `_build_school_overview_context()`
- `xjtlu-rag-system/ollama_client.py`
  - `embed_text()`
  - `_ollama_embed()`
  - `_openai_embed()`
  - `generate_text()`
  - `_openai_generate()`
  - `_ollama_generate()`
- `xjtlu-rag-system/vector_store.py`
  - `init_vector_db()`
  - `search()`
  - `SearchResult`
- `xjtlu-rag-system/memory_store.py`
  - `init_memory_db()`
  - `get_profile()`
  - `add_message()`
  - `recent_messages()`

### Input

HTTP:

```text
POST /chat
Content-Type: application/json
{
  "message": "...",
  "session_id": "..."
}
```

启动配置：

- `RAG_SERVER_HOST`
- `RAG_SERVER_PORT`
- `SOURCE_DB`
- `RAG_DB`
- `MEMORY_DB`
- `EMBED_PROVIDER`
- `EMBED_MODEL`
- `OLLAMA_BASE_URL`
- `CHAT_PROVIDER`
- `CHAT_MODEL`
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `TOP_K`
- `SIMILARITY_THRESHOLD`

默认数据文件：

- `xjtlu-rag-system/xjtlu_knowledge.db`
- `xjtlu-rag-system/rag_index.db`
- `runtime/xjtlu_chat_memory.db`

### Process

`app.py::lifespan()`：

1. `init_vector_db(settings.rag_db)`，确保 `chunks` 表存在。
2. `init_memory_db(settings.memory_db)`，确保 `user_profile` 和 `messages` 表存在。

`app.py::chat_api(request)`：

```text
return await chat(request.session_id, request.message)
```

`chat_engine.py::chat()` 检索路径：

1. 用户画像和历史：
   - `get_profile(settings.memory_db, session_id)`
   - `upsert_profile(...)`
   - `add_message(..., "user", message)`
   - `recent_messages(..., limit=8)`
2. 判断是否需要 RAG：
   - `_needs_rag(message)` 对学校、专业、招生、课程等关键词返回 true。
3. 向量检索：
   - `embed_text(message)`
   - 如果 `EMBED_PROVIDER=ollama`，调用 `OLLAMA_BASE_URL/api/embed`，失败 404 时回退 `/api/embeddings`。
   - 如果 `EMBED_PROVIDER=openai`，调用 `OPENAI_BASE_URL/embeddings`。
   - `vector_store.search()` 从 `rag_index.db` 的 `chunks` 表读全部 embedding，用 cosine similarity 排序，保留 `score >= SIMILARITY_THRESHOLD` 的 top K。
4. 直接 SQL 补充：
   - `_build_direct_faq_context()` 查询 `SOURCE_DB` 的 `faq` 表。
   - `_build_programme_context()` 查询 `programmes` 表。
   - `_build_school_overview_context()` 查询 `school_info` 表。
5. LLM 生成：
   - `generate_text(prompt, system)`
   - `CHAT_PROVIDER=openai` 时调用 `OPENAI_BASE_URL/chat/completions`。
   - `CHAT_PROVIDER=ollama` 时调用 `OLLAMA_BASE_URL/api/generate`。
6. 输出解析：
   - `_parse_json_object()`
   - `_limit_answer()`
   - `_normalize_action()`
   - `add_message(..., "assistant", answer)`

### Output

RAG 返回给 `llm_server.py`：

```json
{
  "answer": "...",
  "action": {
    "label": "...",
    "official_name": "...",
    "action_id": 25,
    "score": 0.8,
    "backend": "deepseek",
    "reason": "..."
  },
  "sources": [],
  "timing": {}
}
```

## 9. 回复文本如何进入 TTS？

### 文件和函数

- `llm_server.py`
  - `infer()`
  - `synthesize_tts()`
  - `tts()`
  - `clean_text()`
  - `detect_language()`
- `llm_surf_context_node.py`
  - `_prepare_tts_wav()`
  - `_write_tts_play_context()`
  - `_request_tts_mp3()`
  - `_convert_tts_to_wav()`
  - `_llm_tts_url()`
- `project_config.py`
  - `ProjectConfig.tts_mp3_path`
  - `ProjectConfig.tts_wav_path`
  - `ProjectConfig.tts_play_context_path`

### Input

- LLM/RAG 返回的 `reply`。
- TTS API：

```text
GET /tts?text=...
```

- runtime path：
  - `LLM_RUNTIME_DIR`
  - 默认 `runtime/`

### Process

`llm_server.py::infer()` 先做一次 TTS：

```text
reply -> clean_text() -> detect_language() -> tts(reply, lang)
```

`tts(text, lang)` 使用 Edge TTS：

- `zh` -> `zh-CN-XiaoxiaoNeural`
- `en` -> `en-US-AriaNeural`
- `ja` -> `ja-JP-NanamiNeural`

输出：

```text
runtime/tts.mp3
```

主链路中，`llm_surf_context_node.py::on_audio_msg()` 收到 `reply` 后调用：

```text
_prepare_tts_wav("reply", reply, session_id)
```

`_prepare_tts_wav()`：

1. `_write_tts_play_context(kind, text, session_id)` 写：

```text
runtime/tts_play_context.json
```

2. `_request_tts_mp3(text)` 调用：

```text
GET http://127.0.0.1:8000/tts?text=...
```

3. `_convert_tts_to_wav()` 调用 ffmpeg：

```text
ffmpeg -y -i runtime/tts.mp3 -ar 16000 -ac 1 runtime/tts.wav
```

唤醒确认和思考确认也复用同一路径：

- `_play_wake_ack()`
- `_play_thinking_ack()`

### Output

- `runtime/tts.mp3`
- `runtime/tts.wav`
- `runtime/tts_play_context.json`

`runtime/tts.wav` 的 mtime 变化是 `unitree_audio_player.py` 播放的触发信号。

## 10. `unitree_audio_player.py` 如何让 G1 播放语音？

### 文件和函数

- `unitree_audio_player.py`
  - `_set_light()`
  - `_refresh_light_loop()`
  - 主循环
- `wav.py`
  - `read_wav()`
  - `play_pcm_stream()`
- Unitree Python SDK：
  - `unitree_sdk2py.core.channel.ChannelFactoryInitialize`
  - `unitree_sdk2py.g1.audio.g1_audio_client.AudioClient`

### Input

文件输入：

- `runtime/tts.wav`
- `runtime/tts_play_context.json`
- `runtime/wake_light_command.json`

配置：

- `UNITREE_ENABLE`
- `UNITREE_DOMAIN_ID`
- `UNITREE_NETWORK_INTERFACE`
- `UNITREE_AUDIO_VOLUME`
- `LLM_RUNTIME_DIR`

脚本入口：

```text
scripts/run_audio_player.sh
-> LLM_PYTHON unitree_audio_player.py
```

### Process

启动时：

1. 如果 `CONFIG.unitree_enable` 为 false，进长 sleep，不连接 G1。
2. 调用：

```text
ChannelFactoryInitialize(CONFIG.unitree_domain_id, CONFIG.unitree_network_interface)
```

3. 初始化音频客户端：

```text
audio_client = AudioClient()
audio_client.SetTimeout(10.0)
audio_client.Init()
audio_client.SetVolume(CONFIG.unitree_audio_volume)
```

4. 启动 `_refresh_light_loop()` 线程。

主循环每 0.2 秒检查：

1. `runtime/wake_light_command.json` mtime 是否变化：
   - 变化后读 JSON，调用 `_set_light()`。
   - `_set_light()` 调用 `audio_client.LedControl(red, green, blue)`。
2. `runtime/tts_play_context.json`：
   - 读取播放类型 `kind`、`session_id`、`text`。
3. `runtime/tts.wav` mtime 是否变化：
   - 变化后调用 `read_wav()`
   - 再调用 `play_pcm_stream(audio_client, pcm_list, "tts")`

`wav.py::play_pcm_stream()`：

1. 把 PCM list 转成 bytes。
2. 生成 `stream_id`。
3. 按 chunk 切分，默认 `chunk_size=96000`。
4. 对每个 chunk 调用：

```text
AudioClient.PlayStream(stream_name, stream_id, chunk)
```

### Output

- G1 扬声器播放 TTS。
- G1 LED 灯颜色变化。
- 会话日志：
  - `tts_play_started`
  - `tts_play_finished`

## 11. 灯光和手臂动作是在哪一层触发的？

## 11.1 灯光

### 文件和函数

- `llm_surf_context_node.py`
  - `_open_wake_listen_window()`
  - `_set_wake_light_red()`
  - `_set_wake_light_green()`
  - `_set_wake_light_blue()`
  - `_set_wake_light_color()`
- `unitree_audio_player.py`
  - `_set_light()`
  - `_refresh_light_loop()`

### Input

事件：

- wake 收到：`on_wake()`
- ASR 进入思考：`on_audio_msg()`
- ASR 为空、忽略、错误、完成：多个分支调用 `_set_wake_light_blue()`

配置：

- `UNITREE_ENABLE`
- `LLM_RUNTIME_DIR`

### Process

`llm_surf_context_node.py` 不直接调用 Unitree LED。它写文件：

```text
runtime/wake_light_command.json
```

`_set_wake_light_color()` 写入字段：

```json
{
  "color": "green",
  "red": 0,
  "green": 255,
  "blue": 0,
  "effect": "blink",
  "updated_at": 0
}
```

颜色语义：

- `_set_wake_light_red()`：唤醒后等待命令。
- `_set_wake_light_green()`：ASR 被接受，进入 thinking。
- `_set_wake_light_blue()`：回复播放或结束后的待机色。

`unitree_audio_player.py` 检测文件变化后调用：

```text
AudioClient.LedControl(red, green, blue)
```

`_refresh_light_loop()` 对 `effect == "blink"` 做闪烁刷新。

### Output

- G1 LED 状态变化。

## 11.2 手臂动作

### 文件和函数

- `llm_surf_context_node.py`
  - `_run_wake_ack_action()`
  - `_run_wake_ack_action_locked()`
  - `_run_thinking_action()`
  - `run_reply_action()`
  - `_run_reply_action_locked()`
  - `_classification_from_deepseek_action()`
  - `_execute_classified_action()`
  - `_run_action_classifier()`
  - `_action_command()`
  - `_runner_command()`
  - `release_arm()`
  - `action_env()`
- `deps/unitree_g1_action_classifier_package/arm_action_classifier/arm_action_classifier.py`
  - `classify_keyword()`
  - `classify_qwen()`
  - `classify_hf()`
  - `execute_action()`
  - `build_runner_env()`
- `deps/unitree_g1_action_classifier_package/unitree_sdk2/example/g1/high_level/g1_arm_action_example.cpp`
  - `G1ArmActionClient`
  - `ExecuteAction()`

### Input

动作来源有三类：

1. Wake ack 动作：
   - `SURF_LLM_WAKE_ACK_ACTION_ENABLE`
   - `SURF_LLM_WAKE_ACK_ACTION_ID`
   - `SURF_LLM_WAKE_ACK_ACTION_LABEL`

2. Thinking 动作：
   - `SURF_LLM_THINKING_ACTION_ENABLE`
   - 调用旧 SDK 示例 `g1_arm7_sdk_dds_example.py`

3. Reply 动作：
   - RAG 返回的 `action` payload。
   - 或动作分类器输出。

关键配置：

- `LLM_ACTION_ENABLE`
- `LLM_ACTION_EXECUTE`
- `LLM_ACTION_BACKEND`
- `LLM_ACTION_THRESHOLD`
- `LLM_ACTION_KEYWORD_FIRST`
- `LLM_ACTION_AUTO_RELEASE`
- `LLM_ACTION_RELEASE_AFTER_SEC`
- `LLM_ACTION_SCRIPT`
- `LLM_ACTION_RUNNER`
- `UNITREE_NETWORK_INTERFACE`

### Process

Wake ack：

```text
on_wake()
-> _maybe_play_wake_ack()
-> _play_wake_ack()
-> _run_wake_ack_action()
-> _run_wake_ack_action_locked()
-> subprocess: LLM_ACTION_RUNNER --network UNITREE_NETWORK_INTERFACE --id SURF_LLM_WAKE_ACK_ACTION_ID
```

Reply action：

```text
on_audio_msg()
-> llm_response = _request_llm(...)
-> action_payload = llm_response.get("action", {})
-> thread run_reply_action(reply, user_text, action_payload)
```

`_run_reply_action_locked()` 的优先级：

1. 如果 `action_payload` 存在：
   - `_classification_from_deepseek_action(action_payload, reply)`
   - `_execute_classified_action(classification)`
2. 如果没有 payload 且 `LLM_ACTION_KEYWORD_FIRST=1`：
   - `_run_action_classifier(user_text, "keyword")`
3. 如果仍没有 payload 且 `LLM_ACTION_BACKEND not in ("deepseek", "none")`：
   - `_run_action_classifier(reply, CONFIG.action_backend)`
4. 如果仍没有动作：
   - `_no_action_classification()`

`_execute_classified_action()`：

1. 检查 `action_id`、`should_execute`、`LLM_ACTION_EXECUTE`、runner 是否存在。
2. 运行：

```text
LLM_ACTION_RUNNER --network UNITREE_NETWORK_INTERFACE --id action_id
```

3. 解析输出：
   - `invalid_fsm_id`
   - `arm_holding_release_required`
   - `runner_reported_failure`
   - `runner_nonzero_returncode`
   - `runner_completed`

`action_env()` 会给 subprocess 增加：

- `NO_PROXY`
- `no_proxy`
- `LD_LIBRARY_PATH=.../unitree_sdk2/thirdparty/lib/<arch>`

C++ runner：

`g1_arm_action_example.cpp` 初始化 DDS：

```text
ChannelFactory::Instance()->Init(0, network)
```

然后：

```text
G1ArmActionClient client
client.Init()
client.SetTimeout(10.f)
client.ExecuteAction(id)
```

### Output

- G1 执行官方预置手臂动作。
- `runtime/status.json` 更新：
  - `last_action`
  - `last_action_id`
  - `last_action_score`
  - `last_action_backend`
  - `last_action_executed`
  - `last_action_reason`
- `logs/<session>/pipeline.log` 记录：
  - `wake_ack_action_result`
  - `action_result`
  - `session_end`

## 12. 配置和接口索引

### ROS2 topics

| Topic | Type | Producer | Consumer | 内容 |
| --- | --- | --- | --- | --- |
| `/wake_word_event` | `std_msgs/msg/String` | `SurfRosBridge._poll()` | `LlmSurfContextNode.on_wake()` | wake word、session_id、time |
| `/vad_state` | `std_msgs/msg/Bool` | `SurfRosBridge._poll()` | `LlmSurfContextNode.on_vad()` | 是否检测到 speech |
| `/speaker_id` | `std_msgs/msg/String` | `SurfRosBridge._poll()` | `LlmSurfContextNode.on_speaker()` | speaker、score |
| `/audio_msg` | `std_msgs/msg/String` | `SurfRosBridge._poll()` | `LlmSurfContextNode.on_audio_msg()` | ASR text、speaker、session_id、time |

### HTTP APIs

| API | Method | Provider | Caller | 用途 |
| --- | --- | --- | --- | --- |
| `/health` | GET | `llm_server.py` | `scripts/run_pipeline.sh` | LLM server 健康检查 |
| `/infer` | GET | `llm_server.py` | `LlmSurfContextNode._request_llm()` | 文本生成 + action + mp3 TTS |
| `/tts` | GET | `llm_server.py` | `LlmSurfContextNode._request_tts_mp3()` | 单独生成 mp3 TTS |
| `/health` | GET | `xjtlu-rag-system/app.py` | `scripts/run_pipeline.sh` | RAG server 健康检查 |
| `/chat` | POST | `xjtlu-rag-system/app.py` | `llm_server.py::post_rag_chat()` | RAG 检索、DeepSeek 回答、动作选择 |
| `/api/embed` | POST | Ollama | `ollama_client._ollama_embed()` | 生成 embedding |
| `/api/embeddings` | POST | Ollama | `ollama_client._ollama_embed()` | embedding fallback |
| `/chat/completions` | POST | DeepSeek/OpenAI-compatible | `ollama_client._openai_generate()` | RAG LLM 生成 |
| `/chat/completions` | POST | DashScope | `llm_server.post_chat_completion()` | `LLM_REPLY_BACKEND=dashscope` |

### Runtime files

| Path | Writer | Reader | 用途 |
| --- | --- | --- | --- |
| `runtime/tts.mp3` | `llm_server.py::tts()` | `LlmSurfContextNode._convert_tts_to_wav()` | Edge TTS mp3 |
| `runtime/tts.wav` | `LlmSurfContextNode._convert_tts_to_wav()` | `unitree_audio_player.py` | G1 播放源 |
| `runtime/tts_play_context.json` | `LlmSurfContextNode._write_tts_play_context()` | `unitree_audio_player.py` | 播放 kind/session/text |
| `runtime/wake_light_command.json` | `LlmSurfContextNode._set_wake_light_color()` | `unitree_audio_player.py` | LED 指令 |
| `runtime/status.json` | `LlmSurfContextNode._update_status()` | 人/监控脚本 | pipeline 状态 |
| `runtime/surf_context_status.json` | `LlmSurfContextNode._write_status()` | 人/监控脚本 | SURF context 状态 |
| `runtime/xjtlu_chat_memory.db` | RAG memory store | RAG memory store | 用户画像和对话历史 |

### 关键配置文件

- `config/default.env`
  - 主链路所有默认配置。
- `config/local.env`
  - 本机覆盖和密钥。
- `project_config.py`
  - `ProjectConfig` 把 env 转成 Python 配置。
- `deps/SURF2026_VoiceModule-main/config/default.env`
  - SURF voice 默认配置。
- `deps/SURF2026_VoiceModule-main/config/voice_config.py`
  - `VoiceConfig`。
- `xjtlu-rag-system/rag_config.py`
  - `Settings`。

## 13. 单次交互的最短时序

```text
1. 用户说唤醒词
2. RobotMicCapture._recv_loop()
3. AudioBus.push()
4. ChineseWakeWordDetector 检出 wake
5. SurfVoiceRuntime._on_wake()
6. UdpEventSink.publish("/wake_word_event")
7. SurfRosBridge._poll() -> ROS2 /wake_word_event
8. LlmSurfContextNode.on_wake()
9. _set_wake_light_red()
10. _play_wake_ack() -> llm_server /tts -> runtime/tts.wav
11. unitree_audio_player.py -> AudioClient.PlayStream()
12. 用户说命令
13. VAD speech/silence 驱动 ASR stop
14. ASREngine.stop_and_transcribe()
15. SurfVoiceRuntime._on_asr()
16. UdpEventSink.publish("/audio_msg")
17. SurfRosBridge._poll() -> ROS2 /audio_msg
18. LlmSurfContextNode.on_audio_msg()
19. _request_llm() -> llm_server /infer
20. llm_server.infer() -> RAG /chat 或 dashscope/local
21. chat_engine.chat() -> history + vector search + direct SQL context + LLM JSON
22. llm_server.clean_text() + tts() -> runtime/tts.mp3
23. LlmSurfContextNode._prepare_tts_wav() -> /tts -> ffmpeg -> runtime/tts.wav
24. unitree_audio_player.py detects tts.wav mtime
25. read_wav() -> play_pcm_stream() -> AudioClient.PlayStream()
26. run_reply_action() -> LLM_ACTION_RUNNER -> G1ArmActionClient.ExecuteAction()
```
