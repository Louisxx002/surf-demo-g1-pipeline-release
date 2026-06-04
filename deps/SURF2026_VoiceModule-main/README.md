# SURF2026 Voice Module

Unitree G1 语音处理模块，负责机器人麦克风输入、唤醒词识别、VAD、ASR 和声纹识别。

## 模块结构

```
voice_module/
├── audio/          # 麦克风采集 + AudioBus
├── wake_word/      # 唤醒词检测 + 去重分发
├── vad/            # 语音活动检测
├── doa/            # 声源方位识别
├── asr/            # 语音识别
├── config/         # 统一配置
├── ros_nodes/      # ROS2 节点入口
└── scripts/        # 启动脚本
```

## Pipeline

```
G1 Mic -> AudioBus -> Wake Word -> VAD -> ASR -> /audio_msg -> Qwen Pipeline
                         └──────────────-> speaker_id / voice context
```

## 环境

Ubuntu 24.04 + ROS2 Jazzy + conda `voice` 环境

## 依赖安装

```bash
conda activate voice
pip install -r requirements.txt
```

## 当前集成默认值

```text
VOICE_AUDIO_SOURCE=robot
VOICE_ASR_WINDOW_SEC=8.0
VOICE_VAD_HOLDOFF_SEC=4.0
VOICE_VAD_SILENCE_FRAMES=75
```

含义：

```text
唤醒后开始录音；检测到用户开口后取消 ASR 硬截止；
用户停顿约 1.5 秒后触发转写。
```
