# SURF2026 Voice Module Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在宇树G1机器人上实现音频级唤醒词识别、嘈杂人声滤波、声源方位识别，通过ROS2 `/audio_msg` 接入队友王嘉康现有的 Qwen+TTS pipeline。

**Architecture:** 麦克风采集 → AudioBus（1秒滚动缓冲+多消费者）→ 噪声抑制前处理 → 并行运行唤醒词检测（openWakeWord）和VAD（webrtcvad）→ 唤醒后触发ASR（FunASR）→ 发布 `/audio_msg`；多通道原始PCM同时送 DOA（pyroomacoustics MUSIC）→ 发布 `/voice_direction`。AudioBus 和 WakeupDispatcher 参考 AgentOS 的设计思路，代码独立编写。

**Tech Stack:** Ubuntu 24.04 · ROS2 Jazzy · conda `voice` (Python 3.10) · openWakeWord · webrtcvad · noisereduce · pyroomacoustics · FunASR · sounddevice · pytest

---

## Review 注意事项

> 本节是对整个实现计划的审查补充，执行前必读。

---

### 1. 代码合规：AgentOS 参考边界

你在 RIVOTEK 实习时接触的 AgentOS 代码属于公司知识产权。本项目是 XJTLU 学术科研项目（SURF），两者性质不同，**必须严格区分**：

| 允许 | 不允许 |
|---|---|
| 参考 AudioBus 的"1s缓冲+多消费者"设计思路 | 将 AudioBus.kt 逐行翻译成 Python |
| 参考 WakeupDispatcher 的去重逻辑（500ms窗口）| 复制任何 RIVOTEK 代码片段，即使改了变量名 |
| 使用相同的开源库（webrtcvad、openWakeWord）| 使用 RIVOTEK 采购的商业 SDK（讯飞CAE、AISpeech）|
| 在 README 中注明"设计参考自车载语音系统实践经验" | 不可引用 AgentOS 代码仓库地址或内部文档 |

**执行原则**：所有代码从开源库文档和公开资料出发，独立编写。设计思路可以"一样"，代码实现必须"全新"。

---

### 2. 代码规范

**命名**
- 模块、文件：`snake_case.py`
- 类：`PascalCase`
- 常量：`UPPER_CASE`（置于模块顶部）
- 私有属性/方法：`_single_underscore` 前缀

**类型注解**
- 所有公共方法必须有完整 type hints（参数+返回值）
- 使用 `from __future__ import annotations` 启用延迟求值

**注释原则**（参考项目整体风格）
- 不写"做什么"的注释，变量名和方法名应自描述
- 只写"为什么"：非显而易见的设计决策、绕过的特定 bug、硬件约束
- 类级别 docstring 只写一行说明核心职责

**格式**
- 行长不超过 100 字符
- 使用 4 空格缩进（不用 Tab）
- import 顺序：标准库 → 第三方 → 本项目，各组之间空一行

---

### 3. 提交规范

使用 **Conventional Commits** 格式：

```
<type>(<scope>): <简短描述（英文，不超过72字符）>
```

**type 列表：**

| type | 场景 |
|---|---|
| `feat` | 新功能 |
| `fix` | bug 修复 |
| `test` | 新增或修改测试 |
| `refactor` | 重构（不改功能） |
| `docs` | 文档变更 |
| `chore` | 构建、依赖、配置变更 |

**实际示例：**
```
feat(audio_bus): add 1s rolling buffer with consumer isolation
test(wakeup_dispatcher): add dedup window boundary tests
fix(vad_engine): guard against wrong frame size input
chore(deps): add noisereduce and funasr to requirements
```

**提交粒度原则：**
- 每个 Task 至少一个 commit，不要把多个模块塞进同一个 commit
- 测试和实现可以放同一个 commit（TDD 模式），也可以分开
- 不要 commit 未通过测试的代码

---

### 4. 关键技术风险与规避

#### ⚠️ 风险1：openWakeWord 默认模型只有英文

openWakeWord 预训练模型支持 `hey jarvis`、`alexa` 等英文唤醒词。你们设定的 **"西浦小g"** 不在其中，直接使用会无法触发。

**规避方案（分阶段）：**
- **Phase 1-2**：用英文唤醒词（`hey gee`）先跑通整个管道，验证架构正确性
- **Phase 3**：使用 [openWakeWord 自定义训练流程](https://github.com/dscripka/openWakeWord#custom-models) 训练"西浦小g"模型，约需 500 条录音样本
- **备选**：sherpa-onnx 支持中文自定义唤醒词，模型训练更简单，可作为备用方案

#### ⚠️ 风险2：WSL2 麦克风访问

WSL2 NAT 模式下，`sounddevice` 无法直接访问 Windows 物理麦克风（Ubuntu 看不到音频设备）。

**规避方案：**
- Phase 1（单元测试）：全部 mock，不需要麦克风，不受影响
- Phase 2+（需要真实音频）：在**实验室 Ubuntu 机器**上测试，或配置 WSLg + PulseAudio（复杂，不推荐）
- 在代码中把麦克风设备号做成配置项（`VOICE_MIC_DEVICE`），方便切换 USB 麦和机器人内置麦

#### ⚠️ 风险3：WakeWordDetector._buffer 线程安全

计划中的 `push_audio()` 从 AudioBus 回调线程修改 `self._buffer`，但 `_run()` 线程也读取队列。目前 `_buffer` 的修改不受锁保护，在高频推送下可能出现竞态。

**修复**：在 `push_audio()` 中加锁保护 `_buffer`，或改为使用线程安全的 `queue.Queue` 直接传整块 chunk（已在实现方案中处理，执行时注意验证）。

#### ⚠️ 风险4：noisereduce 实时延迟

`noisereduce.reduce_noise()` 是离线批量算法，每次处理约 100ms，会造成音频管道延迟叠加。

**规避方案：**
- 可以接受：在唤醒词检测前加 NS，检测结果延迟 100ms 是可接受的
- 如果实测延迟太高：改用 `scipy.signal` 的简单高通滤波器（延迟近乎为零，但降噪效果弱），或评估 `speexdsp`（RNNoise）

#### ⚠️ 风险5：DOA 方位歧义（2麦问题）

2 只麦克风只能给出声源在两个候选方向之一（前/后对称歧义）。`_DEFAULT_MIC_POS` 中使用 2 麦的方案，**无法区分正前方和正后方**。

**规避方案：**
- 确认 G1 实际可用麦克风数量，如果有 ≥3 麦可完全规避
- 如果确实只有 2 麦，需要结合 G1 的 IMU 或摄像头做辅助判断
- DOA 输出结果报告中需说明此限制

#### ⚠️ 风险6：G1 麦克风输入 API 未确认

目前 `unitree_sdk2_python` 中 `g1_audio_client.py` 只有播放接口（`PlayStream`），**没有看到麦克风录音接口**。

**行动项**：与王嘉康确认 G1 音频输入方式。可能的情况：
1. G1 麦克风通过 DDS topic 推送原始 PCM → 改用 ROS2 订阅替代 `sounddevice`
2. G1 没有可用麦克风 API → 外接 USB 麦克风阵列（推荐 ReSpeaker 4-Mic，Linux 免驱）
3. 需要联系宇树技术支持获取文档

#### ⚠️ 风险7：FunASR 首次运行需要下载模型

`paraformer-zh` 约 200MB，首次 import 时自动从 ModelScope 下载。在没有网络的实验室环境可能失败。

**规避**：提前在有网络的环境运行一次让模型缓存，或手动下载模型文件到本地路径并配置 `model_path`。

---

### 5. 与王嘉康 Pipeline 接入注意

- `/audio_msg` 格式：现有代码兼容 JSON `{"text": "..."}` 和纯文本，我们发 JSON 即可
- 现有代码已有**文本层唤醒词过滤**（`strip_wake_word`），我们加音频层后，文本层可保留作为安全网（防止 ASR 误识别绕过唤醒词检测）
- 确认双方的 `UNITREE_DOMAIN_ID` 和 `UNITREE_NETWORK_INTERFACE` 配置一致，否则 DDS 无法发现

---

### 6. 开源许可证合规（学术项目必须注明）

| 库 | 许可证 | 使用方式 |
|---|---|---|
| openWakeWord | Apache 2.0 | 直接使用，需在 README 注明 |
| webrtcvad | BSD-3-Clause | 直接使用，需注明 |
| pyroomacoustics | MIT | 直接使用，需注明 |
| FunASR | MIT | 直接使用，需注明 |
| noisereduce | MIT | 直接使用，需注明 |
| ROS2 Jazzy | Apache 2.0 | 框架，需注明 |

在 `README.md` 中加一个 `## Acknowledgements` 节列出以上库。

---

## 文件结构总览

```
code/voice_module/
├── config/
│   └── voice_config.py          # 统一配置，frozen dataclass，读env var
├── audio/
│   ├── __init__.py
│   ├── audio_bus.py             # 1s滚动缓冲 + 多消费者分发（移植自AgentOS AudioBus）
│   ├── mic_capture.py           # sounddevice 麦克风采集，推送到 AudioBus
│   └── audio_preprocessor.py   # ABC接口 + noisereduce NS实现
├── wake_word/
│   ├── __init__.py
│   ├── wake_word_detector.py    # openWakeWord 封装，消费 AudioBus
│   └── wakeup_dispatcher.py    # 500ms去重+回调（移植自AgentOS WakeupDispatcher）
├── vad/
│   ├── __init__.py
│   └── vad_engine.py            # webrtcvad 封装，20ms帧检测
├── doa/
│   ├── __init__.py
│   └── doa_processor.py         # pyroomacoustics MUSIC算法，输出方位角
├── asr/
│   ├── __init__.py
│   └── asr_engine.py            # FunASR paraformer-zh 封装，唤醒后录音+转写
├── ros_nodes/
│   ├── __init__.py
│   └── voice_pipeline_node.py   # ROS2主节点，串联全部模块
├── tests/
│   ├── conftest.py              # pytest fixtures（合成音频、mock AudioBus）
│   ├── test_audio_bus.py
│   ├── test_wakeup_dispatcher.py
│   ├── test_vad_engine.py
│   ├── test_wake_word_detector.py
│   ├── test_audio_preprocessor.py
│   ├── test_asr_engine.py
│   └── test_doa_processor.py
├── scripts/
│   └── run_pipeline.sh          # 启动脚本
├── requirements.txt
└── docs/plans/
    └── 2026-04-30-voice-module.md  # 本文件
```

**ROS2 Topic 接口：**

| Topic | 类型 | 说明 |
|---|---|---|
| `/audio_msg` | `std_msgs/String` | JSON `{"text": "..."}` 送往 Qwen pipeline |
| `/voice_direction` | `std_msgs/Float32` | 声源方位角（0–360°） |
| `/wake_word_event` | `std_msgs/String` | 唤醒词名称（调试用） |
| `/vad_state` | `std_msgs/Bool` | 当前是否检测到人声 |

---

## Chunk 1: 测试基础设施 + 配置 + AudioBus

> **可以在 PC 上完成，不需要真机或麦克风。**

---

### Task 1: 测试基础设施与配置

**Files:**
- Create: `config/voice_config.py`
- Create: `tests/conftest.py`
- Modify: `requirements.txt`

- [ ] **Step 1: 更新 requirements.txt，加入开发依赖**

```
openwakeword
webrtcvad-wheels
pyaudio
sounddevice
soundfile
pyroomacoustics
numpy
scipy
noisereduce
funasr
modelscope
pytest
```

- [ ] **Step 2: 安装新依赖**

```bash
conda activate voice
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple noisereduce pytest
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple funasr modelscope
```

> FunASR 首次 import 会自动下载模型，约 200MB，需要网络。

- [ ] **Step 3: 写 voice_config.py**

```python
# config/voice_config.py
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)

def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v is not None else default

def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v is not None else default

def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    v = os.environ.get(name)
    if not v:
        return default
    return tuple(s.strip() for s in v.split(",") if s.strip())

@dataclass(frozen=True)
class VoiceConfig:
    sample_rate: int              = _env_int("VOICE_SAMPLE_RATE", 16000)
    channels: int                 = _env_int("VOICE_CHANNELS", 1)
    frame_ms: int                 = _env_int("VOICE_FRAME_MS", 20)
    audio_bus_buffer_sec: float   = _env_float("VOICE_BUS_BUFFER_SEC", 1.0)

    mic_device: int | None        = None

    wake_words: tuple[str, ...]   = _env_list("VOICE_WAKE_WORDS", ("hey jarvis", "alexa"))
    wake_threshold: float         = _env_float("VOICE_WAKE_THRESHOLD", 0.5)
    wakeup_dedup_sec: float       = _env_float("VOICE_WAKEUP_DEDUP_SEC", 0.5)

    asr_model: str                = _env("VOICE_ASR_MODEL", "paraformer-zh")
    asr_window_sec: float         = _env_float("VOICE_ASR_WINDOW_SEC", 5.0)

    ros_audio_topic: str          = _env("VOICE_ROS_AUDIO_TOPIC", "/audio_msg")
    ros_direction_topic: str      = _env("VOICE_ROS_DIRECTION_TOPIC", "/voice_direction")
    ros_wake_topic: str           = _env("VOICE_ROS_WAKE_TOPIC", "/wake_word_event")
    ros_vad_topic: str            = _env("VOICE_ROS_VAD_TOPIC", "/vad_state")

    @property
    def frame_bytes(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000) * 2

CONFIG = VoiceConfig()
```

- [ ] **Step 4: 写 conftest.py**

```python
# tests/conftest.py
import numpy as np
import pytest
from config.voice_config import CONFIG

def _sine_pcm(freq: float = 440.0, duration_sec: float = 0.1,
              sample_rate: int = 16000) -> bytes:
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    wave = (np.sin(2 * np.pi * freq * t) * 32767 * 0.5).astype(np.int16)
    return wave.tobytes()

def _silence_pcm(duration_sec: float = 0.1, sample_rate: int = 16000) -> bytes:
    n = int(sample_rate * duration_sec)
    return (np.zeros(n, dtype=np.int16)).tobytes()

@pytest.fixture
def sine_pcm():
    return _sine_pcm()

@pytest.fixture
def silence_pcm():
    return _silence_pcm()

@pytest.fixture
def one_frame_pcm():
    return _silence_pcm(duration_sec=CONFIG.frame_ms / 1000)
```

- [ ] **Step 5: 验证 pytest 可以收集**

```bash
cd /mnt/e/Education/Research/SURF2026_RobotAgent/code/voice_module
conda activate voice
python -m pytest tests/ --collect-only
```

预期：`no tests ran`，无报错

---

### Task 2: AudioBus

**Files:**
- Create: `audio/audio_bus.py`
- Create: `tests/test_audio_bus.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_audio_bus.py
import threading
from audio.audio_bus import AudioBus

def test_consumer_receives_pushed_chunk():
    bus = AudioBus()
    received = []
    bus.register("test", received.append)
    bus.push(b"\x01\x02")
    assert received == [b"\x01\x02"]

def test_multiple_consumers_all_receive():
    bus = AudioBus()
    a, b = [], []
    bus.register("a", a.append)
    bus.register("b", b.append)
    bus.push(b"hello")
    assert a == [b"hello"]
    assert b == [b"hello"]

def test_faulty_consumer_does_not_block_others():
    bus = AudioBus()
    good = []
    def bad(chunk): raise RuntimeError("boom")
    bus.register("bad", bad)
    bus.register("good", good.append)
    bus.push(b"data")
    assert good == [b"data"]

def test_unregister_stops_delivery():
    bus = AudioBus()
    received = []
    bus.register("c", received.append)
    bus.unregister("c")
    bus.push(b"after")
    assert received == []

def test_backtrack_returns_last_1s_of_audio():
    bus = AudioBus()
    chunk = b"\x00" * 1024
    for _ in range(32):
        bus.push(chunk)
    bt = bus.get_backtrack()
    assert len(bt) == 31 * 1024

def test_push_is_thread_safe():
    bus = AudioBus()
    results = []
    bus.register("r", results.append)
    threads = [threading.Thread(target=bus.push, args=(b"x",)) for _ in range(50)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(results) == 50
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_audio_bus.py -v
```

- [ ] **Step 3: 实现 audio_bus.py**

```python
# audio/audio_bus.py
from __future__ import annotations
import threading
from collections import deque
from typing import Callable
from config.voice_config import CONFIG

_FRAME_BYTES = 1024
_MAX_FRAMES = int(CONFIG.audio_bus_buffer_sec * CONFIG.sample_rate * 2 / _FRAME_BYTES)


class AudioBus:
    """
    1秒滚动音频缓冲 + 多消费者分发。
    移植自 AgentOS AudioBus.kt：消费者异常隔离，线程安全。
    """

    def __init__(self) -> None:
        self._consumers: dict[str, Callable[[bytes], None]] = {}
        self._buffer: deque[bytes] = deque(maxlen=_MAX_FRAMES)
        self._lock = threading.Lock()

    def register(self, name: str, callback: Callable[[bytes], None]) -> None:
        with self._lock:
            self._consumers[name] = callback

    def unregister(self, name: str) -> None:
        with self._lock:
            self._consumers.pop(name, None)

    def push(self, pcm_chunk: bytes) -> None:
        with self._lock:
            self._buffer.append(pcm_chunk)
            consumers = dict(self._consumers)
        for name, cb in consumers.items():
            try:
                cb(pcm_chunk)
            except Exception as exc:
                print(f"[AudioBus] consumer '{name}' raised: {exc}")

    def get_backtrack(self) -> bytes:
        with self._lock:
            return b"".join(self._buffer)
```

- [ ] **Step 4: 运行，确认通过**

```bash
python -m pytest tests/test_audio_bus.py -v
```

预期：6 passed

---

### Task 3: WakeupDispatcher

**Files:**
- Create: `wake_word/wakeup_dispatcher.py`
- Create: `tests/test_wakeup_dispatcher.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_wakeup_dispatcher.py
import time
from unittest.mock import MagicMock
from wake_word.wakeup_dispatcher import WakeupDispatcher

def test_dispatch_calls_callback():
    cb = MagicMock()
    d = WakeupDispatcher(on_wake=cb)
    assert d.dispatch("hey jarvis") is True
    cb.assert_called_once_with("hey jarvis")

def test_dedup_within_window_ignored():
    cb = MagicMock()
    d = WakeupDispatcher(on_wake=cb, dedup_sec=0.5)
    d.dispatch("hey jarvis")
    d.dispatch("hey jarvis")
    assert cb.call_count == 1

def test_dedup_after_window_allowed():
    cb = MagicMock()
    d = WakeupDispatcher(on_wake=cb, dedup_sec=0.05)
    d.dispatch("hey jarvis")
    time.sleep(0.1)
    d.dispatch("hey jarvis")
    assert cb.call_count == 2

def test_different_wake_words_not_deduped():
    cb = MagicMock()
    d = WakeupDispatcher(on_wake=cb)
    d.dispatch("hey jarvis")
    d.dispatch("alexa")
    assert cb.call_count == 2

def test_faulty_callback_does_not_raise():
    def bad(word): raise RuntimeError("boom")
    d = WakeupDispatcher(on_wake=bad)
    assert d.dispatch("hey jarvis") is True
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_wakeup_dispatcher.py -v
```

- [ ] **Step 3: 实现 wakeup_dispatcher.py**

```python
# wake_word/wakeup_dispatcher.py
from __future__ import annotations
import threading
import time
from typing import Callable
from config.voice_config import CONFIG


class WakeupDispatcher:
    """
    唤醒词去重分发器。移植自 AgentOS WakeupDispatcher.kt。
    同一唤醒词在 dedup_sec 内只触发一次。
    """

    def __init__(self, on_wake: Callable[[str], None],
                 dedup_sec: float = CONFIG.wakeup_dedup_sec) -> None:
        self._on_wake = on_wake
        self._dedup_sec = dedup_sec
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def dispatch(self, wake_word: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last.get(wake_word, 0.0) < self._dedup_sec:
                return False
            self._last[wake_word] = now
        try:
            self._on_wake(wake_word)
        except Exception as exc:
            print(f"[WakeupDispatcher] on_wake raised: {exc}")
        return True
```

- [ ] **Step 4: 运行，确认通过**

```bash
python -m pytest tests/test_wakeup_dispatcher.py -v
```

预期：5 passed

---

### Task 4: VAD Engine

**Files:**
- Create: `vad/vad_engine.py`
- Create: `tests/test_vad_engine.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_vad_engine.py
import numpy as np
import pytest
from vad.vad_engine import VADEngine, FRAME_BYTES

def make_frame(amplitude: float = 0.0) -> bytes:
    n = FRAME_BYTES // 2
    wave = (np.ones(n) * amplitude * 32767).astype(np.int16)
    return wave.tobytes()

def test_silence_returns_false():
    vad = VADEngine(aggressiveness=2)
    assert vad.is_speech(make_frame(0.0)) is False

def test_wrong_frame_size_returns_false():
    vad = VADEngine()
    assert vad.is_speech(b"\x00" * 10) is False

def test_aggressiveness_range():
    for level in (0, 1, 2, 3):
        VADEngine(aggressiveness=level)

def test_invalid_aggressiveness_raises():
    with pytest.raises(AssertionError):
        VADEngine(aggressiveness=4)
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_vad_engine.py -v
```

- [ ] **Step 3: 实现 vad_engine.py**

```python
# vad/vad_engine.py
import webrtcvad
from config.voice_config import CONFIG

FRAME_DURATION_MS = CONFIG.frame_ms
SAMPLE_RATE = CONFIG.sample_rate
FRAME_BYTES = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000) * 2  # 640 bytes @ 20ms


class VADEngine:
    """webrtcvad 封装。aggressiveness 0(宽松)~3(激进)，推荐2。"""

    def __init__(self, aggressiveness: int = 2) -> None:
        assert 0 <= aggressiveness <= 3
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, pcm_frame: bytes) -> bool:
        if len(pcm_frame) != FRAME_BYTES:
            return False
        return self._vad.is_speech(pcm_frame, SAMPLE_RATE)
```

- [ ] **Step 4: 运行，确认通过**

```bash
python -m pytest tests/test_vad_engine.py -v
```

预期：4 passed

- [ ] **Step 5: Chunk 1 全量验证**

```bash
python -m pytest tests/ -v
```

预期：15 passed，0 failed

---

## Chunk 2: 唤醒词检测 + 噪声抑制 + ASR

> **Phase 2，需要 PC 麦克风，不需要 G1 真机。**

---

### Task 5: 噪声抑制预处理器

**Files:**
- Create: `audio/audio_preprocessor.py`
- Create: `tests/test_audio_preprocessor.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_audio_preprocessor.py
import numpy as np
from audio.audio_preprocessor import NoiseReduceProcessor

def make_noisy_pcm(duration_sec: float = 0.1, sample_rate: int = 16000) -> bytes:
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec))
    signal = np.sin(2 * np.pi * 440 * t) * 32767 * 0.5
    noise = np.random.randn(len(t)) * 3000
    return (signal + noise).astype(np.int16).tobytes()

def test_output_same_length_as_input():
    proc = NoiseReduceProcessor()
    raw = make_noisy_pcm()
    assert len(proc.process(raw)) == len(raw)

def test_output_is_bytes():
    proc = NoiseReduceProcessor()
    assert isinstance(proc.process(make_noisy_pcm()), bytes)

def test_on_far_end_does_not_raise():
    proc = NoiseReduceProcessor()
    proc.on_far_end(b"\x00" * 640)
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_audio_preprocessor.py -v
```

- [ ] **Step 3: 实现 audio_preprocessor.py**

```python
# audio/audio_preprocessor.py
from __future__ import annotations
from abc import ABC, abstractmethod
import numpy as np
import noisereduce as nr
from config.voice_config import CONFIG


class AudioPreprocessor(ABC):
    """
    音频前处理抽象接口。移植自 AgentOS AudioPreprocessor.kt。
    process(): 输入原始PCM，返回降噪后同等长度PCM。
    on_far_end(): AEC远端参考（TTS输出），子类按需实现。
    """
    @abstractmethod
    def process(self, raw_pcm: bytes) -> bytes: ...

    def on_far_end(self, ref_pcm: bytes) -> None:
        pass


class NoiseReduceProcessor(AudioPreprocessor):
    """基于 noisereduce 的稳态噪声抑制。适合空调/风扇等静态背景噪声。"""

    def __init__(self, sample_rate: int = CONFIG.sample_rate) -> None:
        self._sample_rate = sample_rate

    def process(self, raw_pcm: bytes) -> bytes:
        audio = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
        reduced = nr.reduce_noise(y=audio, sr=self._sample_rate, stationary=True)
        return reduced.astype(np.int16).tobytes()
```

- [ ] **Step 4: 运行，确认通过**

```bash
python -m pytest tests/test_audio_preprocessor.py -v
```

预期：3 passed

---

### Task 6: 唤醒词检测器

**Files:**
- Create: `wake_word/wake_word_detector.py`
- Create: `tests/test_wake_word_detector.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_wake_word_detector.py
import time
from unittest.mock import MagicMock, patch
from wake_word.wake_word_detector import WakeWordDetector, CHUNK_BYTES

def test_push_audio_buffers_correctly():
    with patch("wake_word.wake_word_detector.Model"):
        det = WakeWordDetector(on_detected=MagicMock())
        det.push_audio(b"\x01" * CHUNK_BYTES)
        assert len(det._buffer) < CHUNK_BYTES

def test_start_and_stop_do_not_raise():
    with patch("wake_word.wake_word_detector.Model"):
        det = WakeWordDetector(on_detected=MagicMock())
        det.start()
        time.sleep(0.05)
        det.stop()

def test_on_detected_called_when_score_above_threshold():
    cb = MagicMock()
    with patch("wake_word.wake_word_detector.Model") as MockModel:
        MockModel.return_value.predict.return_value = {"hey jarvis": 0.9}
        det = WakeWordDetector(on_detected=cb, threshold=0.5)
        det.start()
        det.push_audio(b"\x00" * CHUNK_BYTES)
        time.sleep(0.2)
        det.stop()
    cb.assert_called_with("hey jarvis")

def test_on_detected_not_called_below_threshold():
    cb = MagicMock()
    with patch("wake_word.wake_word_detector.Model") as MockModel:
        MockModel.return_value.predict.return_value = {"hey jarvis": 0.2}
        det = WakeWordDetector(on_detected=cb, threshold=0.5)
        det.start()
        det.push_audio(b"\x00" * CHUNK_BYTES)
        time.sleep(0.2)
        det.stop()
    cb.assert_not_called()
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_wake_word_detector.py -v
```

- [ ] **Step 3: 实现 wake_word_detector.py**

```python
# wake_word/wake_word_detector.py
from __future__ import annotations
import queue
import threading
from typing import Callable
import numpy as np
from openwakeword.model import Model
from config.voice_config import CONFIG

CHUNK_SAMPLES = 1280        # openWakeWord 期望 80ms @ 16kHz
CHUNK_BYTES = CHUNK_SAMPLES * 2


class WakeWordDetector:
    """
    openWakeWord 封装，作为 AudioBus 消费者运行。
    push_audio() 由 AudioBus 回调（任意线程），内部队列隔离避免阻塞分发。
    """

    def __init__(self, on_detected: Callable[[str], None],
                 model_paths: list[str] | None = None,
                 threshold: float = CONFIG.wake_threshold) -> None:
        self._model = Model(wakeword_models=model_paths, inference_framework="onnx")
        self._on_detected = on_detected
        self._threshold = threshold
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=50)
        self._buffer = b""
        self._running = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._running = True
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def push_audio(self, pcm: bytes) -> None:
        self._buffer += pcm
        while len(self._buffer) >= CHUNK_BYTES:
            chunk, self._buffer = self._buffer[:CHUNK_BYTES], self._buffer[CHUNK_BYTES:]
            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                pass

    def _run(self) -> None:
        while self._running:
            try:
                chunk = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            for word, score in self._model.predict(audio).items():
                if score >= self._threshold:
                    self._on_detected(word)
```

- [ ] **Step 4: 运行，确认通过**

```bash
python -m pytest tests/test_wake_word_detector.py -v
```

预期：4 passed

---

### Task 7: ASR Engine

**Files:**
- Create: `asr/asr_engine.py`
- Create: `tests/test_asr_engine.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_asr_engine.py
import numpy as np
from unittest.mock import MagicMock, patch
from asr.asr_engine import ASREngine

def make_pcm(duration_sec: float = 0.5) -> bytes:
    n = int(16000 * duration_sec)
    return (np.zeros(n, dtype=np.int16)).tobytes()

def test_start_clears_buffer():
    with patch("asr.asr_engine.AutoModel"):
        engine = ASREngine(on_result=MagicMock())
        engine._buffer = b"old"
        engine.start_recording()
        assert engine._buffer == b""

def test_push_when_recording():
    with patch("asr.asr_engine.AutoModel"):
        engine = ASREngine(on_result=MagicMock())
        engine.start_recording()
        engine.push_audio(b"\x01" * 100)
        assert engine._buffer == b"\x01" * 100

def test_push_when_not_recording_ignored():
    with patch("asr.asr_engine.AutoModel"):
        engine = ASREngine(on_result=MagicMock())
        engine.push_audio(b"\x01" * 100)
        assert engine._buffer == b""

def test_stop_calls_model_and_callback():
    cb = MagicMock()
    with patch("asr.asr_engine.AutoModel") as MockModel:
        MockModel.return_value.generate.return_value = [{"text": "你好世界"}]
        engine = ASREngine(on_result=cb)
        engine.start_recording()
        engine.push_audio(make_pcm(0.5))
        engine.stop_and_transcribe()
    cb.assert_called_once_with("你好世界")

def test_empty_buffer_no_callback():
    cb = MagicMock()
    with patch("asr.asr_engine.AutoModel"):
        engine = ASREngine(on_result=cb)
        engine.start_recording()
        engine.stop_and_transcribe()
    cb.assert_not_called()
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_asr_engine.py -v
```

- [ ] **Step 3: 实现 asr_engine.py**

```python
# asr/asr_engine.py
from __future__ import annotations
import threading
from typing import Callable
import numpy as np
from funasr import AutoModel
from config.voice_config import CONFIG


class ASREngine:
    """
    FunASR paraformer-zh 封装。
    唤醒词触发 start_recording() → AudioBus 持续 push_audio()
    → VAD静音或超时触发 stop_and_transcribe() → on_result 回调。
    """

    def __init__(self, on_result: Callable[[str], None],
                 model_name: str = CONFIG.asr_model) -> None:
        self._model = AutoModel(model=model_name, disable_update=True)
        self._on_result = on_result
        self._buffer = b""
        self._recording = False
        self._lock = threading.Lock()

    def start_recording(self) -> None:
        with self._lock:
            self._recording = True
            self._buffer = b""

    def push_audio(self, pcm: bytes) -> None:
        with self._lock:
            if self._recording:
                self._buffer += pcm

    def stop_and_transcribe(self) -> None:
        with self._lock:
            self._recording = False
            audio_data = self._buffer
        if not audio_data:
            return
        audio = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        result = self._model.generate(input=audio, batch_size_s=300)
        text = result[0]["text"].strip() if result else ""
        if text:
            self._on_result(text)
```

- [ ] **Step 4: 运行，确认通过**

```bash
python -m pytest tests/test_asr_engine.py -v
```

预期：5 passed

- [ ] **Step 5: Chunk 2 全量验证**

```bash
python -m pytest tests/ -v
```

预期：27 passed，0 failed

---

## Chunk 3: 麦克风采集 + ROS2 主节点

> **需要 WSL2 Ubuntu 环境（`source /opt/ros/jazzy/setup.bash`），不需要 G1 真机。**

---

### Task 8: MicCapture

**Files:**
- Create: `audio/mic_capture.py`
- Create: `tests/test_mic_capture.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_mic_capture.py
from unittest.mock import MagicMock, patch
from audio.mic_capture import MicCapture
from audio.audio_bus import AudioBus

def test_start_opens_stream():
    bus = AudioBus()
    with patch("audio.mic_capture.sd.RawInputStream") as MockStream:
        mc = MicCapture(audio_bus=bus)
        mc.start()
        MockStream.assert_called_once()
        mc.stop()

def test_callback_pushes_to_bus():
    received = []
    bus = AudioBus()
    bus.register("test", received.append)
    with patch("audio.mic_capture.sd.RawInputStream"):
        mc = MicCapture(audio_bus=bus)
        mc._callback(b"\x01\x02\x03\x04", 2, None, None)
    assert received == [b"\x01\x02\x03\x04"]
```

- [ ] **Step 2: 实现 mic_capture.py**

```python
# audio/mic_capture.py
from __future__ import annotations
import sounddevice as sd
from audio.audio_bus import AudioBus
from config.voice_config import CONFIG

BLOCKSIZE = 1024


class MicCapture:
    """
    sounddevice 麦克风采集，PCM 推入 AudioBus。
    WSL2 中需要 PulseAudio；真机部署时换为 USB 麦设备号或 Unitree SDK2 音频接口。
    """

    def __init__(self, audio_bus: AudioBus,
                 device: int | None = CONFIG.mic_device) -> None:
        self._bus = audio_bus
        self._device = device
        self._stream: sd.RawInputStream | None = None

    def start(self) -> None:
        self._stream = sd.RawInputStream(
            samplerate=CONFIG.sample_rate,
            channels=CONFIG.channels,
            dtype="int16",
            blocksize=BLOCKSIZE,
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, indata: bytes, frames: int, time_info, status) -> None:
        self._bus.push(bytes(indata))
```

- [ ] **Step 3: 运行测试**

```bash
python -m pytest tests/test_mic_capture.py -v
```

预期：2 passed

---

### Task 9: ROS2 主节点

**Files:**
- Create: `ros_nodes/voice_pipeline_node.py`
- Create: `scripts/run_pipeline.sh`

- [ ] **Step 1: 实现 voice_pipeline_node.py**

```python
# ros_nodes/voice_pipeline_node.py
from __future__ import annotations
import json
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Float32, Bool

from config.voice_config import CONFIG
from audio.audio_bus import AudioBus
from audio.mic_capture import MicCapture
from audio.audio_preprocessor import NoiseReduceProcessor
from wake_word.wake_word_detector import WakeWordDetector
from wake_word.wakeup_dispatcher import WakeupDispatcher
from vad.vad_engine import VADEngine, FRAME_BYTES
from asr.asr_engine import ASREngine


class VoicePipelineNode(Node):
    def __init__(self) -> None:
        super().__init__("voice_pipeline_node")

        self._pub_audio = self.create_publisher(String, CONFIG.ros_audio_topic, 10)
        self._pub_wake  = self.create_publisher(String, CONFIG.ros_wake_topic, 10)
        self._pub_vad   = self.create_publisher(Bool,   CONFIG.ros_vad_topic, 10)

        self._bus          = AudioBus()
        self._preprocessor = NoiseReduceProcessor()
        self._asr          = ASREngine(on_result=self._on_asr_result)
        self._vad          = VADEngine(aggressiveness=2)
        self._dispatcher   = WakeupDispatcher(on_wake=self._on_wake)
        self._detector     = WakeWordDetector(on_detected=self._dispatcher.dispatch)
        self._mic          = MicCapture(audio_bus=self._bus)

        self._bus.register("wake_word", self._detector.push_audio)
        self._bus.register("vad",       self._vad_consumer)
        self._bus.register("asr",       self._asr.push_audio)

        self._asr_timer: threading.Timer | None = None

        self._detector.start()
        self._mic.start()
        self.get_logger().info("VoicePipelineNode ready")
        self.get_logger().info(f"Publishing to: {CONFIG.ros_audio_topic}")

    def _vad_consumer(self, chunk: bytes) -> None:
        for i in range(0, len(chunk), FRAME_BYTES):
            frame = chunk[i:i + FRAME_BYTES]
            msg = Bool()
            msg.data = self._vad.is_speech(frame)
            self._pub_vad.publish(msg)

    def _on_wake(self, wake_word: str) -> None:
        self.get_logger().info(f"Wake word: {wake_word}")
        msg = String()
        msg.data = wake_word
        self._pub_wake.publish(msg)

        self._asr.start_recording()
        if self._asr_timer:
            self._asr_timer.cancel()
        self._asr_timer = threading.Timer(CONFIG.asr_window_sec, self._trigger_transcribe)
        self._asr_timer.start()

    def _trigger_transcribe(self) -> None:
        self._asr.stop_and_transcribe()

    def _on_asr_result(self, text: str) -> None:
        self.get_logger().info(f"ASR: {text}")
        msg = String()
        msg.data = json.dumps({"text": text}, ensure_ascii=False)
        self._pub_audio.publish(msg)

    def destroy_node(self) -> None:
        self._mic.stop()
        self._detector.stop()
        if self._asr_timer:
            self._asr_timer.cancel()
        super().destroy_node()


def main() -> None:
    rclpy.init()
    node = VoicePipelineNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 写启动脚本**

```bash
#!/bin/bash
# scripts/run_pipeline.sh
set -e
source /opt/ros/jazzy/setup.bash
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
echo "Starting Voice Pipeline Node..."
python "$SCRIPT_DIR/ros_nodes/voice_pipeline_node.py"
```

- [ ] **Step 3: 手动集成测试**

```bash
# 终端1：启动节点
cd /mnt/e/Education/Research/SURF2026_RobotAgent/code/voice_module
conda activate voice && source /opt/ros/jazzy/setup.bash
export PYTHONPATH=$(pwd):$PYTHONPATH
python ros_nodes/voice_pipeline_node.py

# 终端2：监听 ASR 输出
source /opt/ros/jazzy/setup.bash
ros2 topic echo /audio_msg

# 终端3：监听唤醒词事件
ros2 topic echo /wake_word_event
```

对着麦克风说唤醒词，终端2应收到 ASR 文字。

---

## Chunk 4: DOA 声源方位识别

> **Phase 4，需要确认 G1 麦克风阵列几何参数，或接入外置 USB 阵列（如 ReSpeaker 4-Mic）。**

---

### Task 10: DOA Processor

**Files:**
- Create: `doa/doa_processor.py`
- Create: `tests/test_doa_processor.py`

- [ ] **Step 1: 确认麦克风阵列几何（接入真机前必做）**

需要确认：
- G1 头部/胸部麦克风数量和物理间距（单位：米）
- 或 ReSpeaker 4-Mic 阵列规格（正方形，边长约 4.5cm）

- [ ] **Step 2: 写失败测试**

```python
# tests/test_doa_processor.py
import numpy as np
from doa.doa_processor import DOAProcessor

def make_multi_ch_pcm(n_ch: int = 2, duration_sec: float = 0.1,
                      sample_rate: int = 16000) -> bytes:
    n = int(sample_rate * duration_sec)
    audio = (np.random.randn(n, n_ch) * 1000).astype(np.int16)
    return audio.tobytes()

def test_estimate_returns_float():
    proc = DOAProcessor(n_channels=2)
    angle = proc.estimate(make_multi_ch_pcm(2), n_channels=2)
    assert isinstance(angle, float)

def test_estimate_angle_in_range():
    proc = DOAProcessor(n_channels=2)
    angle = proc.estimate(make_multi_ch_pcm(2), n_channels=2)
    assert 0.0 <= angle < 360.0

def test_custom_mic_positions():
    mic_pos = np.array([[0.0, 0.10], [0.0, 0.0]])
    proc = DOAProcessor(mic_positions=mic_pos, n_channels=2)
    angle = proc.estimate(make_multi_ch_pcm(2), n_channels=2)
    assert 0.0 <= angle < 360.0
```

- [ ] **Step 3: 实现 doa_processor.py**

```python
# doa/doa_processor.py
from __future__ import annotations
import numpy as np
import pyroomacoustics as pra
from config.voice_config import CONFIG

# 占位几何：线性2麦，间距5cm（接真机后替换）
_DEFAULT_MIC_POS = np.array([[0.0, 0.05], [0.0, 0.0]])


class DOAProcessor:
    """
    pyroomacoustics MUSIC 算法，估计声源方位角（0–360°）。
    接入真实麦克风阵列后，将 mic_positions 替换为实际几何参数。
    """

    def __init__(self, mic_positions: np.ndarray | None = None,
                 n_channels: int = 2,
                 sample_rate: int = CONFIG.sample_rate,
                 nfft: int = 256) -> None:
        self._n_channels = n_channels
        self._sample_rate = sample_rate
        self._nfft = nfft
        self._mic_positions = mic_positions if mic_positions is not None else _DEFAULT_MIC_POS

    def estimate(self, multi_channel_pcm: bytes, n_channels: int | None = None) -> float:
        n_ch = n_channels or self._n_channels
        audio = np.frombuffer(multi_channel_pcm, dtype=np.int16).astype(np.float32)
        audio = audio.reshape(-1, n_ch).T / 32768.0
        X = np.array([np.fft.rfft(ch, n=self._nfft) for ch in audio])
        doa = pra.doa.MUSIC(self._mic_positions[:, :n_ch], self._sample_rate,
                            nfft=self._nfft, num_src=1)
        doa.locate_sources(X[:, :, np.newaxis])
        return float(np.degrees(doa.azimuth_recon[0])) % 360.0
```

- [ ] **Step 4: 集成到 voice_pipeline_node.py**

在 `__init__` 中新增：

```python
from doa.doa_processor import DOAProcessor
self._pub_dir = self.create_publisher(Float32, CONFIG.ros_direction_topic, 10)
self._doa = DOAProcessor(n_channels=CONFIG.channels)
self._bus.register("doa", self._doa_consumer)
```

新增方法：

```python
def _doa_consumer(self, chunk: bytes) -> None:
    try:
        angle = self._doa.estimate(chunk, n_channels=CONFIG.channels)
        msg = Float32()
        msg.data = float(angle)
        self._pub_dir.publish(msg)
    except Exception as e:
        self.get_logger().debug(f"DOA skipped: {e}")
```

- [ ] **Step 5: 全量测试**

```bash
python -m pytest tests/ -v
```

预期：全部 passed

---

## 端到端联调（需要 G1 真机）

```bash
# 机器人侧（王嘉康的3个终端）
./scripts/run_server.sh
./scripts/run_ros_node.sh
./scripts/run_audio_player.sh

# 语音模块侧
conda activate voice
source /opt/ros/jazzy/setup.bash
export PYTHONPATH=/path/to/voice_module:$PYTHONPATH
bash scripts/run_pipeline.sh
```

说出唤醒词后说一句话，G1 应语音回复。

---

## Phase 总结

| Phase | Chunk | 内容 | 需要真机？ |
|---|---|---|---|
| 1 | 1 | AudioBus + WakeupDispatcher + VADEngine | ❌ 纯单元测试 |
| 2 | 2 | AudioPreprocessor + WakeWordDetector + ASREngine | ❌ PC麦即可 |
| 3 | 3 | MicCapture + ROS2主节点 | ❌ WSL2即可 |
| 4 | 4 | DOA + 真机接入 | ✅ 需G1或USB麦阵列 |
