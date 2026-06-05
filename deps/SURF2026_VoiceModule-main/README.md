# SURF2026 Voice Module

Unitree G1 语音处理模块，负责机器人麦克风输入、唤醒词识别、VAD、ASR 和声纹识别。

## 模块结构

```
voice_module/
├── audio/          # 麦克风采集 + AudioBus
├── tools/          # USB/机器人麦录音和 UDP 推流调试脚本
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

## USB 麦克风 UDP 接入

机器人原生麦默认走 `239.168.123.161:5555`。外置 USB 麦可以在机器人上转发到电脑的 `5556` 端口：

```bash
# 机器人 SSH 终端
python3 tools/stream_usb_mic.py --port 5556
```

电脑端接入：

```bash
VOICE_AUDIO_SOURCE=robot VOICE_ROBOT_MIC_PORT=5556 python run_robot.py
```

在集成 workspace 里运行完整 pipeline 时同样使用端口覆盖：

```bash
VOICE_ROBOT_MIC_PORT=5556 ./scripts/run_pipeline.sh --mode wake
```
