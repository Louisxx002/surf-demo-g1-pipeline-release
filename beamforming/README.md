# 固定波束形成模块

本目录将老师提供的 MATLAB 固定波束形成算法转换为 Python，并把离线算法与实时音频传输分开。

## 已确认事实

- 老师参考输入 `mixture.wav` 是 16 kHz、PCM16、4 通道。
- 分析窗为 32 ms（512 samples），hop 为 16 ms（256 samples）。
- 每次输入“四路 16 ms 信号”表示 `256 samples x 4 channels`，不是 64 个通道。
- 老师确认机器人 USB 设备按 8 通道录制，前 4 路为有效麦克风信号；默认映射为 `(0, 1, 2, 3)`。
- 每次正式接入前仍需核对 8 路录音电平，确认前 4 路有信号、后 4 路无有效语音，防止设备或驱动状态变化。
- 现有 `stream_usb_mic.py` 会先将全部通道求平均，因此当前 UDP 数据无法用于波束形成。

## 目录职责

- `fixed_mini_beamformer.py`：离线与有状态流式算法核心。
- `filter_io.py`：加载不依赖 SciPy 的运行时 `.npz` 滤波器。
- `stream_adapter.py`：从 8 路 PCM16 选 4 路，执行 16 ms-hop 波束处理，再打包为原协议的 20 ms 单声道 UDP payload。
- `channel_diagnostics.py`：通道电平、静音、削波、重复和相关性分析。

## 离线验证

```bash
cd ~/surf_sync/surf-demo-g1-pipeline-release
PY=/home/alina/miniconda3/envs/voice312/bin/python
REF=research/beamforming/teacher_reference_20260630

$PY tools/beamforming/verify_teacher_reference.py "$REF"
$PY tools/beamforming/apply_fixed_beamformer_wav.py \
  "$REF/mixture.wav" \
  "$REF/DCF_Targ7_runtime.npz" \
  "$REF/python_out0.wav"
```

当前验收结果：最大误差 1 LSB、RMSE 约 0.00259 LSB、仅 6 个采样点与老师输出不同。

## 下次真机采集

先通过 `arecord -l` 自动确认 Bothlent UAC Dongle 当前 ALSA 编号，再把诊断脚本复制到 Jetson。示例中的 `hw:2,0` 不能长期写死：

```bash
python3 tools/beamforming/capture_multichannel_alsa.py \
  /tmp/bothlent_raw8.wav \
  --device hw:2,0 \
  --channels 8 \
  --sample-rate 16000 \
  --duration 10
```

将 WAV 拿回电脑后运行：

```bash
$PY tools/beamforming/analyze_multichannel_wav.py /path/to/bothlent_raw8.wav
```

逐个靠近四只物理麦克风说话或轻触，核对前 4 路均有有效信号，并记录它们的物理顺序。当前默认 `channel_indices=(0,1,2,3)`；若实测不符，使用机器本地配置显式覆盖，不修改算法核心。

## 安全接入原则

1. 保留当前 `mean` 模式作为回滚路径。
2. `beamformer` 模式必须明确加载滤波器和四路映射，配置缺失时直接报错。
3. Jetson 端在 UDP 发送前处理，WSL 端仍接收 16 kHz、PCM16、mono、20 ms、640 bytes，因此下游 KWS/VAD/ASR 无需修改。
4. 不在 WSL 直接初始化 Unitree `AudioClient`；TTS、灯光和动作继续走 Jetson relay。
