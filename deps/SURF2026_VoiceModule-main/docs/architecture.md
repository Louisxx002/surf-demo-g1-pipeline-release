# SURF2026 Voice Module 架构

## Pipeline

```
麦克风(USB) → 噪声抑制 → AudioBus ─┬─ 唤醒词检测(openWakeWord)
                                   ├─ VAD(webrtcvad)
                                   ├─ ASR(FunASR paraformer-zh) → /audio_msg → Qwen Pipeline
                                   └─ DOA声源方位(pyroomacoustics) → /voice_direction
```

## 模块结构

```
voice_module/
├── config/
│   └── voice_config.py          # 统一配置（采样率、唤醒词、ROS话题等）
├── audio/
│   ├── audio_bus.py             # 线程安全PCM广播总线，1秒滚动缓冲 ✅
│   ├── audio_preprocessor.py   # 噪声抑制（noisereduce）
│   └── mic_capture.py          # sounddevice麦克风采集
├── wake_word/
│   ├── wake_word_detector.py   # openWakeWord封装
│   └── wakeup_dispatcher.py    # 唤醒词去重分发，500ms窗口 ✅
├── vad/
│   └── vad_engine.py           # webrtcvad帧级VAD，20ms帧 ✅
├── asr/
│   └── asr_engine.py           # FunASR paraformer-zh，唤醒后转写
├── doa/
│   └── doa_processor.py        # pyroomacoustics MUSIC算法，4声道
├── ros_nodes/
│   └── voice_pipeline_node.py  # ROS2主节点，串联全部模块
└── tests/                      # 18个单元测试 ✅

✅ = 已完成并通过测试
```

## ROS2 接口

| Topic | 类型 | 说明 |
|---|---|---|
| `/audio_msg` | std_msgs/String | JSON {"text":"..."} → Qwen |
| `/voice_direction` | std_msgs/Float32 | 声源方位角 0–360° |
| `/wake_word_event` | std_msgs/String | 唤醒词名称 |
| `/vad_state` | std_msgs/Bool | 是否检测到人声 |
