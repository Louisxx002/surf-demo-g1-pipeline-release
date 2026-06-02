# 中文唤醒词检测器 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `ChineseWakeWordDetector`，用 sherpa-onnx `KeywordSpotter` 实现任意中文唤醒词检测，接口与现有 `WakeWordDetector` 完全一致，`VoicePipelineNode` 通过配置项切换。

**Architecture:** `ChineseWakeWordDetector` 与 `WakeWordDetector` 采用同样的双线程架构——`push_audio()` 在 AudioBus 回调线程中积累 PCM，后台推理线程消费 queue 并调用 sherpa-onnx 推理。`VoicePipelineNode` 根据 `CONFIG.wake_word_lang`（`"en"` / `"zh"`）在构造时选择对应检测器，其余代码无需改动。唤醒词通过 `CONFIG.kws_keywords`（音素字符串）在运行时配置，无需重新训练模型。

**Tech Stack:** sherpa-onnx `KeywordSpotter`（zipformer KWS ONNX 模型），Python threading + queue，现有 `WakeupDispatcher` 不变。

> ⚠️ **背景说明（为什么不用 FunASR）：**  
> 原计划使用 FunASR `iic/speech_fsmn_kws_zh-cn`，但该模型在 ModelScope 上返回 404，FunASR model_zoo 中也无任何 KWS 模型。调研 AgentOS（同组实习项目）后确认其中文唤醒词使用 **sherpa-onnx** 实现，经验证方案可行，故切换。

---

## 文件清单

| 操作 | 路径 | 职责 |
|---|---|---|
| **Create** | `wake_word/chinese_wake_word_detector.py` | sherpa-onnx KeywordSpotter 封装，接口同 WakeWordDetector |
| **Create** | `tests/test_chinese_wake_word_detector.py` | 5 个单元测试，mock sherpa_onnx |
| **Create** | `models/kws/keywords.txt` | 唤醒词音素文件（占位，上机前填入确认词） |
| **Modify** | `config/voice_config.py` | 新增 `kws_model_dir`、`kws_keywords` 两个字段 |
| **Modify** | `ros_nodes/voice_pipeline_node.py` | 根据 lang 配置项选择检测器 |

---

## Chunk 1：环境 + Config + 模型准备

### Task 1：安装 sherpa-onnx 并下载模型

**背景：** sherpa-onnx 提供预训练 zipformer KWS ONNX 模型，支持中文关键词检测，无需训练。  
模型目录结构（下载后）：
```
models/kws/
  encoder.onnx
  decoder.onnx
  joiner.onnx
  tokens.txt
  keywords.txt      ← 我们手动维护的唤醒词文件
```

- [ ] **Step 1：安装 sherpa-onnx**

```bash
conda activate voice
pip install sherpa-onnx
python -c "import sherpa_onnx; print(sherpa_onnx.__version__)"
```

期望：打印出版本号（≥ 1.10.0）

- [ ] **Step 2：将模型目录加入 .gitignore**

ONNX 文件体积大，不应提交到 git。在 `code/voice_module/.gitignore`（或项目根 `.gitignore`）中添加：

```
# sherpa-onnx KWS model files
models/kws/*.onnx
models/kws/*.tar.bz2
```

`tokens.txt` 和 `keywords.txt` 体积小、需要版本控制，**不加进 .gitignore**。

- [ ] **Step 3：下载中文 KWS 模型**

```bash
cd code/voice_module/models
# 创建目录
mkdir -p kws && cd kws

# 下载 sherpa-onnx 预训练中文 zipformer KWS 模型（约 3.3MB）
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2
tar xf sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2 --strip-components=1
ls -lh *.onnx tokens.txt
```

期望：看到 `encoder.onnx`、`decoder.onnx`、`joiner.onnx`、`tokens.txt`

- [ ] **Step 4：验证模型可加载及 Python API 调用链**

```bash
cd code/voice_module
python -c "
import sherpa_onnx, pathlib, numpy as np
model_dir = pathlib.Path('models/kws')
kws = sherpa_onnx.KeywordSpotter(
    tokens=str(model_dir / 'tokens.txt'),
    encoder=str(model_dir / 'encoder.onnx'),
    decoder=str(model_dir / 'decoder.onnx'),
    joiner=str(model_dir / 'joiner.onnx'),
    keywords_buf='你 好 小 G @你好小G\n',
    num_trailing_blanks=2,
    provider='cpu',
)
# 同时验证 Python API 调用链
stream = kws.create_stream()
silence = np.zeros(3200, dtype=np.float32)
stream.accept_waveform(sample_rate=16000, waveform=silence)
kws.decode_stream(stream)
result = kws.get_result(stream)
print('OK, result on silence:', repr(result))  # 期望 ''
"
```

期望：打印出 `OK: <KeywordSpotter ...>`，无报错

---

### Task 2：voice_config.py 新增 KWS 字段

**Files:**
- Modify: `config/voice_config.py`（当前 `wake_word_lang` 行下方）

**背景：**
- `kws_model_dir`：模型文件目录，默认 `models/kws`（相对于 voice_module 根目录）
- `kws_keywords`：音素格式的唤醒词字符串，直接传给 `keywords_buf`。  
  格式：`<token1> <token2> ... @<显示名>\n`（多个词换行分隔）  
  示例（占位）：`你 好 小 G @你好小G\n`  
  ⚠️ 上机前需确认唤醒词并填写正确音素，当前为占位值，可通过环境变量 `VOICE_KWS_KEYWORDS` 覆盖

- [ ] **Step 4：在 `wake_word_lang` 和 `chinese_wake_words` 行后插入两个新字段**

在 `config/voice_config.py` 的 `chinese_wake_words` 行后插入：

```python
    kws_model_dir: str          = _env("VOICE_KWS_MODEL_DIR",
                                        str(PROJECT_ROOT / "models" / "kws"))
    kws_keywords: str           = _env("VOICE_KWS_KEYWORDS", "你 好 小 G @你好小G\n")
```

完成后该段落应为：

```python
    wake_words: tuple[str, ...] = _env_list("VOICE_WAKE_WORDS", ("hey jarvis", "alexa"))
    wake_threshold: float       = _env_float("VOICE_WAKE_THRESHOLD", 0.5)
    wake_word_lang: str         = _env("VOICE_WAKE_WORD_LANG", "zh")
    chinese_wake_words: str     = _env("VOICE_CHINESE_WAKE_WORDS", "你好小G")
    kws_model_dir: str          = _env("VOICE_KWS_MODEL_DIR",
                                        str(PROJECT_ROOT / "models" / "kws"))
    kws_keywords: str           = _env("VOICE_KWS_KEYWORDS", "你 好 小 G @你好小G\n")
    wakeup_dedup_sec: float     = _env_float("VOICE_WAKEUP_DEDUP_SEC", 0.5)
```

- [ ] **Step 5：验证 config 可正常导入**

```bash
cd code/voice_module
python -c "from config.voice_config import CONFIG; print(CONFIG.kws_model_dir); print(repr(CONFIG.kws_keywords))"
```

期望：打印出 models/kws 的绝对路径，以及 `'你 好 小 G @你好小G\n'`

---

## Chunk 2：ChineseWakeWordDetector 实现 + 测试

### Task 3：写测试（TDD：先写测试，再写实现）

**Files:**
- Create: `tests/test_chinese_wake_word_detector.py`

**背景：** sherpa-onnx 是重型依赖，测试中用 `unittest.mock.patch` mock 掉 `sherpa_onnx`，只测逻辑行为。  
mock 策略：`sherpa_onnx.KeywordSpotter` → `MockKWS`，`MockKWS().create_stream()` → `mock_stream`，`MockKWS().get_result(stream)` 返回 `""` 或检测到的关键词字符串。

- [ ] **Step 6：创建测试文件**

```python
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from wake_word.chinese_wake_word_detector import CHUNK_BYTES, ChineseWakeWordDetector


def _make_detector(on_detected=None, keywords="你 好 小 G @你好小G\n"):
    if on_detected is None:
        on_detected = MagicMock()
    with patch("wake_word.chinese_wake_word_detector.sherpa_onnx") as mock_shnx:
        mock_kws = MagicMock()
        mock_stream = MagicMock()
        mock_kws.create_stream.return_value = mock_stream
        mock_kws.get_result.return_value = ""  # 默认无检测
        mock_shnx.KeywordSpotter.return_value = mock_kws
        det = ChineseWakeWordDetector(on_detected=on_detected, keywords=keywords)
    det._kws = mock_kws
    det._stream = mock_stream
    return det, on_detected


def _pcm(n_bytes: int) -> bytes:
    return b"\x00" * n_bytes


# ── tests ────────────────────────────────────────────────────────────────────

def test_push_before_start_does_not_infer():
    det, cb = _make_detector()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.05)
    det._kws.decode_stream.assert_not_called()
    cb.assert_not_called()


def test_detection_fires_callback():
    cb = MagicMock()
    det, _ = _make_detector(on_detected=cb)
    det._kws.get_result.return_value = "你好小G"

    det.start()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.3)
    det.stop()

    cb.assert_called_once_with("你好小G")


def test_no_detection_no_callback():
    cb = MagicMock()
    det, _ = _make_detector(on_detected=cb)
    det._kws.get_result.return_value = ""

    det.start()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.3)
    det.stop()

    cb.assert_not_called()


def test_stream_reset_after_detection():
    """检测到后应重建 stream，防止同一帧连续触发。"""
    det, _ = _make_detector()
    det._kws.get_result.return_value = "你好小G"
    old_stream = det._stream

    det.start()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.3)
    det.stop()

    det._kws.create_stream.assert_called()  # 至少调用过一次重建


def test_callback_exception_does_not_crash():
    cb = MagicMock(side_effect=RuntimeError("boom"))
    det, _ = _make_detector(on_detected=cb)
    det._kws.get_result.return_value = "你好小G"

    det.start()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.3)
    det.stop()  # 不应该抛出
```

- [ ] **Step 7：在实现之前先跑测试，确认全部 FAIL**

```bash
cd code/voice_module
bash run_tests.sh -k test_chinese_wake_word_detector 2>&1 | tail -10
```

期望：`ImportError`（模块不存在）或 `ModuleNotFoundError`

---

### Task 4：实现 ChineseWakeWordDetector

**Files:**
- Create: `wake_word/chinese_wake_word_detector.py`

**背景：** sherpa-onnx `KeywordSpotter` 关键 API：

```python
import sherpa_onnx

kws = sherpa_onnx.KeywordSpotter(
    tokens="models/kws/tokens.txt",
    encoder="models/kws/encoder.onnx",
    decoder="models/kws/decoder.onnx",
    joiner="models/kws/joiner.onnx",
    keywords_buf="你 好 小 G @你好小G\n",  # 音素 + @显示名
    num_trailing_blanks=2,
    provider="cpu",
)

stream = kws.create_stream()

# 每帧喂入 float32 音频
samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
stream.accept_waveform(sample_rate=16000, waveform=samples)
kws.decode_stream(stream)

result = kws.get_result(stream)  # "" = 未检测到；非空字符串 = 检测到的关键词
```

检测到后需**重建 stream**（`kws.create_stream()`），防止同一段音频连续触发。

chunk 大小选 **200ms = 3200 samples = 6400 bytes**，推理频率约 5 次/秒。

- [ ] **Step 8：创建实现文件**

```python
from __future__ import annotations

import logging
import pathlib
import queue
import threading
from typing import Callable

import numpy as np

import sherpa_onnx

from config.voice_config import CONFIG

logger = logging.getLogger(__name__)

CHUNK_SAMPLES = 3200   # 200ms @ 16kHz
CHUNK_BYTES   = CHUNK_SAMPLES * 2  # 16-bit PCM


class ChineseWakeWordDetector:
    """sherpa-onnx KeywordSpotter 中文唤醒词检测，接口与 WakeWordDetector 一致。

    push_audio() 在 AudioBus 回调线程调用；后台推理线程消费 queue。
    检测到唤醒词后重建 stream，防止连续触发。
    唤醒词通过 CONFIG.kws_keywords 配置（音素格式），无需重新训练。
    """

    def __init__(
        self,
        on_detected: Callable[[str], None],
        keywords: str = CONFIG.kws_keywords,
        model_dir: str = CONFIG.kws_model_dir,
    ) -> None:
        self._on_detected = on_detected
        self._keywords = keywords

        model = pathlib.Path(model_dir)
        self._kws = sherpa_onnx.KeywordSpotter(
            tokens=str(model / "tokens.txt"),
            encoder=str(model / "encoder.onnx"),
            decoder=str(model / "decoder.onnx"),
            joiner=str(model / "joiner.onnx"),
            keywords_buf=keywords,
            num_trailing_blanks=2,
            provider="cpu",
        )
        self._stream = self._kws.create_stream()

        self._buffer = b""
        self._buffer_lock = threading.Lock()
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=10)
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="zh-wakeword-infer"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def push_audio(self, pcm: bytes) -> None:
        with self._buffer_lock:
            self._buffer += pcm
            while len(self._buffer) >= CHUNK_BYTES:
                chunk = self._buffer[:CHUNK_BYTES]
                self._buffer = self._buffer[CHUNK_BYTES:]
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
            self._infer(chunk)

    def _infer(self, chunk: bytes) -> None:
        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        self._stream.accept_waveform(sample_rate=CONFIG.sample_rate, waveform=samples)
        self._kws.decode_stream(self._stream)
        result = self._kws.get_result(self._stream)

        if result:
            self._stream = self._kws.create_stream()  # 重建 stream，防止连续触发
            try:
                self._on_detected(result)
            except Exception:
                logger.exception("on_detected callback raised")
```

- [ ] **Step 9：跑测试，确认全部 PASS**

```bash
cd code/voice_module
bash run_tests.sh -k test_chinese_wake_word_detector 2>&1 | tail -10
```

期望：`5 passed`

---

## Chunk 3：VoicePipelineNode 切换逻辑 + 集成

### Task 5：VoicePipelineNode 支持 lang 切换

**Files:**
- Modify: `ros_nodes/voice_pipeline_node.py`
- Modify: `tests/test_voice_pipeline_node.py`

**背景：** 现在 `__init__` 里写死了 `WakeWordDetector`。改成根据 `CONFIG.wake_word_lang` 选择。接口完全一致（`start()`、`stop()`、`push_audio()`），其余代码一行都不用动。

- [ ] **Step 10：修改 import 和构造逻辑**

在 `ros_nodes/voice_pipeline_node.py` 顶部 import 区加一行：
```python
from wake_word.chinese_wake_word_detector import ChineseWakeWordDetector
```

将 `__init__` 中的：
```python
self._wakeword = WakeWordDetector(on_detected=self._dispatch.on_detection)
```

替换为：
```python
if CONFIG.wake_word_lang == "zh":
    self._wakeword = ChineseWakeWordDetector(on_detected=self._dispatch.on_detection)
else:
    self._wakeword = WakeWordDetector(on_detected=self._dispatch.on_detection)
```

- [ ] **Step 11：更新 test_voice_pipeline_node.py**

`_make_node()` 的 patch 列表里补上 `ChineseWakeWordDetector`，否则测试会触发真实 sherpa-onnx 导入：

```python
def _make_node():
    with patch("ros_nodes.voice_pipeline_node.WakeWordDetector")        as MockWWD, \
         patch("ros_nodes.voice_pipeline_node.ChineseWakeWordDetector") as MockCWWD, \
         patch("ros_nodes.voice_pipeline_node.ASREngine")               as MockASR, \
         patch("ros_nodes.voice_pipeline_node.VoiceprintRecognizer")    as MockVPR, \
         patch("ros_nodes.voice_pipeline_node.MicCapture")              as MockMic, \
         patch("ros_nodes.voice_pipeline_node.WakeupDispatcher")        as MockDisp:
        node = VoicePipelineNode()
    return node
```

- [ ] **Step 12：跑全部测试，确认全部通过**

```bash
cd code/voice_module
bash run_tests.sh 2>&1 | tail -5
```

期望：`X passed`（原有测试数 + 5 个新测试）

---

## 唤醒词音素配置说明

sherpa-onnx keywords_buf 格式：每行一个关键词，格式为空格分隔的 token + `@显示标签`。  
token 来自模型的 `tokens.txt`，必须与 tokens.txt 中的条目完全匹配。

**配置方式（不改代码）：**
```bash
export VOICE_KWS_KEYWORDS="你 好 小 G @你好小G
"
# 或写入 .env 文件
```

**确认唤醒词后的操作流程：**
1. 查 `models/kws/tokens.txt`，找到唤醒词每个字/音节对应的 token
2. 将 token 序列写入 `VOICE_KWS_KEYWORDS` 环境变量（或更新 `voice_config.py` 默认值）
3. 重启节点即可生效，无需重新训练或重新编译

---

## 上机验证步骤

G1 就位后（WSL2 / Ubuntu 24.04，conda voice 环境）：

1. 确认 sherpa-onnx 模型已就位：
   ```bash
   ls code/voice_module/models/kws/*.onnx
   ```

2. 确认当前 `VOICE_KWS_KEYWORDS` 中的 token 都在 tokens.txt 中：
   ```bash
   python -c "
   from config.voice_config import CONFIG
   tokens = open('models/kws/tokens.txt').read().split()
   for tok in CONFIG.kws_keywords.split():
       if not tok.startswith('@'):
           assert tok in tokens, f'token not found: {tok}'
   print('all tokens OK')
   "
   ```

3. 启动节点，说出唤醒词，确认 `/wake_word_event` 有消息发布：
   ```bash
   VOICE_WAKE_WORD_LANG=zh ros2 topic echo /wake_word_event
   ```

4. 如果漏检率高，尝试：
   - 调整 `num_trailing_blanks`（增大到 3-5）
   - 加长 chunk：`CHUNK_SAMPLES = 4800`（300ms）
   - 检查音素是否与 tokens.txt 完全匹配

5. 如果误触发多，在 `WakeupDispatcher` 层加长去重窗口：
   ```bash
   export VOICE_WAKEUP_DEDUP_SEC=1.0
   ```
