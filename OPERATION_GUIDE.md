# SURF -> Qwen 全流程操作指南

本文档用于在当前工作区跑通 SURF 语音、Qwen、XJTLU RAG、TTS 播放和 Unitree 动作执行的集成流程。

## 1. 进入项目目录

```bash
cd <repo-root>
```

后续命令都默认在这个目录下执行。

## 2. 做环境预检

启动前先检查配置、关键文件和 Python 语法：

```bash
./scripts/check_pipeline.sh
```

正常情况下最后会看到：

```text
SURF -> Qwen workspace check passed.
```

如果这里报错，先不要继续启动全流程，需要根据报错补齐缺失文件、依赖或配置。

## 3. 停掉旧服务

每次重新启动前，建议先停止可能残留的旧服务：

```bash
./scripts/stop_pipeline.sh
```

正常输出：

```text
Stopped SURF -> Qwen integrated pipeline services.
```

## 4. 启动全流程

### 推荐调试模式：持续监听

第一次跑通建议使用 `listen` 模式。该模式不需要唤醒词，启动后可以直接说话测试。

```bash
./scripts/run_pipeline.sh --mode listen
```

### 正常使用模式：唤醒模式

如果要使用唤醒词流程：

```bash
./scripts/run_pipeline.sh --mode wake
```

启动成功后会看到类似输出：

```text
Integrated pipeline started.
SURF publishes /audio_msg; qwen consumes /audio_msg.
Mode: listen
Reply backend: rag
```

当前默认后端是 RAG，全流程链路如下：

```text
语音输入
-> SURF voice runtime
-> /audio_msg
-> qwen_surf_context_node.py
-> qwen_server.py
-> XJTLU RAG
-> DeepSeek reply + action
-> Edge TTS wav
-> audio player
-> Unitree action runner
```

## 5. 查看日志

建议另开一个终端，进入项目目录：

```bash
cd <repo-root>
```

查看全部日志：

```bash
./scripts/tail_pipeline_logs.sh all
```

按模块查看日志：

```bash
./scripts/tail_pipeline_logs.sh voice
./scripts/tail_pipeline_logs.sh rag
./scripts/tail_pipeline_logs.sh qwen
```

也可以直接查看 systemd 用户服务日志：

```bash
journalctl --user -u surf-voice-runtime -f
journalctl --user -u surf-ros-bridge -f
journalctl --user -u surf-qwen-ollama -f
journalctl --user -u surf-qwen-rag -f
journalctl --user -u surf-qwen-server -f
journalctl --user -u surf-qwen-node -f
journalctl --user -u surf-qwen-audio-player -f
```

## 6. 测试语音输入

如果使用持续监听模式：

```bash
./scripts/run_pipeline.sh --mode listen
```

启动成功后，直接对麦克风说话即可。

如果使用唤醒模式：

```bash
./scripts/run_pipeline.sh --mode wake
```

需要先说唤醒词，然后再说指令。当前配置中 `SURF_QWEN_WAKE_WORDS` 为空，如果唤醒不稳定，优先使用 `--mode listen` 跑通主链路。

## 7. 监听 ASR 消息

如果要确认语音识别结果是否发布到 `/audio_msg`，另开终端执行：

```bash
./scripts/monitor_audio_msg.sh
```

如果识别正常，终端里应该能看到语音文本消息。

## 8. 停止全流程

测试结束后执行：

```bash
./scripts/stop_pipeline.sh
```

## 9. 常见问题排查

### 启动卡在 Ollama 或 RAG

查看：

```bash
journalctl --user -u surf-qwen-ollama -f
journalctl --user -u surf-qwen-rag -f
```

### Qwen server 不健康

查看：

```bash
journalctl --user -u surf-qwen-server -f
```

也可以检查 health 接口：

```bash
curl http://127.0.0.1:8000/health
```

### 没有声音回复

查看音频播放器日志：

```bash
journalctl --user -u surf-qwen-audio-player -f
```

### 语音没有进入 Qwen

依次查看：

```bash
journalctl --user -u surf-voice-runtime -f
journalctl --user -u surf-ros-bridge -f
journalctl --user -u surf-qwen-node -f
```

也可以用：

```bash
./scripts/monitor_audio_msg.sh
```

确认 `/audio_msg` 是否有识别文本。

### Unitree 网口没有连接

当前默认网口配置是：

```text
UNITREE_NETWORK_INTERFACE=enp8s0
```

如果该网口未连接或不可用，启动脚本会自动禁用 Unitree DDS，并提示：

```text
Core voice/RAG/DeepSeek pipeline will still start; G1 audio, lights, and action execution are disabled.
```

这种情况下核心语音、RAG 和回复流程仍可运行，但机器人灯光、动作执行、G1 播放相关能力不可用。

## 10. 常用命令汇总

```bash
# 进入项目
cd <repo-root>

# 预检
./scripts/check_pipeline.sh

# 停止旧服务
./scripts/stop_pipeline.sh

# 调试启动：持续监听
./scripts/run_pipeline.sh --mode listen

# 正常启动：唤醒模式
./scripts/run_pipeline.sh --mode wake

# 查看全部日志
./scripts/tail_pipeline_logs.sh all

# 监听 ASR topic
./scripts/monitor_audio_msg.sh

# 停止全流程
./scripts/stop_pipeline.sh
```
