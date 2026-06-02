# Chunk 2 详细设计方案

**日期**：2026-04-30  
**范围**：Task 5 AudioPreprocessor · Task 6 WakeWordDetector · Task 7 ASREngine

---

## 整体数据流

```
AudioBus
  ├─ → NoiseReduceProcessor.process()  → 降噪 PCM（供 WakeWordDetector 消费）
  ├─ → WakeWordDetector.push_audio()   → openWakeWord → on_detected(word)
  │                                              ↓
  │                                    WakeupDispatcher.on_detection()
  │                                              ↓（去重后）
  │                                    _on_wake() → ASREngine.start_recording()
  └─ → ASREngine.push_audio()          → 录音缓冲
                                                 ↓（超时/VAD静音）
                                       ASREngine.stop_and_transcribe()
                                                 ↓
                                       on_result(text) → /audio_msg
```

---

## Task 5: audio/audio_preprocessor.py

### 职责

接受原始 16-bit mono PCM，返回等长降噪 PCM。  
抽象基类保留 AEC 远端参考接口（`on_far_end`），当前阶段用 `NoiseReduceProcessor` 实现。

### 文件

- **Create**: `audio/audio_preprocessor.py`
- **Create**: `tests/test_audio_preprocessor.py`

### 接口设计

```python
class AudioPreprocessor(ABC):
    @abstractmethod
    def process(self, raw_pcm: bytes) -> bytes: ...

    def on_far_end(self, ref_pcm: bytes) -> None:
        pass  # 默认空实现，AEC 场景下子类覆盖


class NoiseReduceProcessor(AudioPreprocessor):
    """noisereduce 稳态降噪，适合空调/风扇背景噪声，约 100ms 批处理延迟。"""
    def __init__(self, sample_rate: int = CONFIG.sample_rate) -> None: ...
    def process(self, raw_pcm: bytes) -> bytes: ...
```

### 关键决策

| 决策 | 原因 |
|---|---|
| `stationary=True` | 实验室环境是稳态噪声（空调/风扇），效果最佳 |
| ABC 接口 | 若延迟太高可无缝换 speexdsp/scipy 高通滤波，不改调用方 |
| 不做 AEC | Phase 2 阶段机器人不播音，回声消除暂不需要 |

### 延迟评估

noisereduce 每帧约 100ms，在 AudioBus → WakeWordDetector 之间加入会导致唤醒词检测延迟约 100ms，可接受。  
若实测延迟超过 300ms，换 `scipy.signal.sosfilt` 高通滤波（近乎零延迟）。

### 测试（3个）

```python
def test_output_same_length_as_input(): ...      # len(output) == len(input)
def test_output_is_bytes(): ...                  # isinstance(output, bytes)
def test_on_far_end_does_not_raise(): ...        # 不抛异常
```

---

## Task 6: wake_word/wake_word_detector.py

### 职责

openWakeWord 封装，作为 AudioBus 消费者。  
AudioBus 回调线程推入 PCM，后台线程负责推理，通过 `on_detected` 回调通知唤醒词名称。

### 文件

- **Create**: `wake_word/wake_word_detector.py`
- **Create**: `tests/test_wake_word_detector.py`

### 关键常量

```python
CHUNK_SAMPLES = 1280   # openWakeWord 期望输入：80ms @ 16kHz
CHUNK_BYTES   = 2560   # CHUNK_SAMPLES * 2（16-bit）
```

### 数据流（线程模型）

```
AudioBus 回调线程
  └─ push_audio(pcm)
       └─ [_buffer_lock] 追加到 self._buffer
            └─ 凑够 CHUNK_BYTES → queue.put_nowait()
                                         ↓
                               _run() 后台 daemon 线程
                                  └─ Model.predict(chunk_float32)
                                       └─ score >= threshold → on_detected(word)
```

### 线程安全修正（对照计划风险3）

计划原版 `push_audio()` 不加锁。虽然 AudioBus 单线程分发（不会有并发调用），  
但为正确性和防御性编程，用 `_buffer_lock` 保护 `self._buffer`：

```python
def push_audio(self, pcm: bytes) -> None:
    with self._buffer_lock:
        self._buffer += pcm
        while len(self._buffer) >= CHUNK_BYTES:
            chunk, self._buffer = self._buffer[:CHUNK_BYTES], self._buffer[CHUNK_BYTES:]
            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                pass  # 推理跟不上时丢弃最旧的 chunk
```

### 推理线程

```python
def _run(self) -> None:
    while self._running:
        try:
            chunk = self._queue.get(timeout=0.1)
        except queue.Empty:
            continue
        # openWakeWord 期望 np.int16，不能归一化为 float32
        audio = np.frombuffer(chunk, dtype=np.int16)
        for word, score in self._model.predict(audio).items():
            if score >= self._threshold:
                try:
                    self._on_detected(word)
                except Exception:
                    logger.exception("on_detected callback raised")
```

> **审查修正1**：`model.predict()` 传 `np.int16`，不做 `/32768.0` 归一化——openWakeWord 内部自行处理。  
> **审查修正2**：`_on_detected` 加 try/except，防止 callback 异常静默杀死后台线程。

### 测试（5个）

所有测试 mock `openwakeword.model.Model`，不实际加载模型文件：

```python
def test_push_audio_buffers_correctly(): ...           # push 后 queue 有数据
def test_start_and_stop_do_not_raise(): ...            # 生命周期无异常
def test_on_detected_called_when_score_above_threshold(): ...  # 超阈值触发
def test_on_detected_not_called_below_threshold(): ...         # 低于阈值不触发
def test_faulty_on_detected_does_not_crash_run_thread(): ...   # callback 异常不崩溃线程
```

> **注意**：超阈值触发测试用 `time.sleep(0.2)` 等待后台线程，CI 极慢环境可加 `@pytest.mark.timeout(2)`。

### Phase 2 限制

openWakeWord 预训练模型仅支持英文（`hey jarvis`、`alexa`）。  
Phase 2 用 `hey jarvis` 验证管道，Phase 3 训练"西浦小g"。

---

## Task 7: asr/asr_engine.py

### 职责

FunASR `paraformer-zh` 封装，实现"唤醒触发 → 录音 → 转写"状态机。

### 文件

- **Create**: `asr/asr_engine.py`
- **Create**: `tests/test_asr_engine.py`

### 状态机

```
IDLE ──start_recording()──► RECORDING ──stop_and_transcribe()──► IDLE
                                 │
                         push_audio() 持续追加 PCM（忽略 IDLE 状态下的推入）
```

### 接口设计

```python
class ASREngine:
    def __init__(self, on_result: Callable[[str], None],
                 model_name: str = CONFIG.asr_model) -> None: ...

    def start_recording(self) -> None: ...       # 清空 buffer，进入 RECORDING
    def push_audio(self, pcm: bytes) -> None: ...  # IDLE 时静默忽略
    def stop_and_transcribe(self) -> None: ...   # 拷贝 buffer → 推理 → on_result
```

### 线程安全

`_lock` 同时保护 `_recording` 和 `_buffer`。  
`stop_and_transcribe()` 先在锁内拷贝 buffer、重置状态，再在锁外调用模型（避免长时持锁阻塞 push_audio）：

```python
def stop_and_transcribe(self) -> None:
    with self._lock:
        self._recording = False
        audio_data = self._buffer
        self._buffer = b""
    if not audio_data:
        return
    # 锁外调用模型（可能耗时数百毫秒）
    audio = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
    result = self._model.generate(input=audio, batch_size_s=300)
    text = result[0].get("text", "").strip() if result else ""  # 审查修正：用 .get 防止 KeyError
    if text:
        self._on_result(text)
```

### FunASR 注意事项

- 首次 `import funasr` 会触发模型下载（paraformer-zh 约 200MB），需要网络
- 测试用 `unittest.mock.patch("asr.asr_engine.AutoModel")` 跳过下载
- 在无网络的实验室环境，提前缓存模型：`AutoModel(model="paraformer-zh")` 跑一次即可

### 测试（5个）

```python
def test_start_clears_buffer(): ...                       # start 后 buffer == b""
def test_push_when_recording(): ...                       # 录音中 push 追加数据
def test_push_when_not_recording_ignored(): ...           # 非录音状态 push 无效
def test_stop_calls_model_and_callback(): ...             # 转写结果通过回调传出
def test_empty_buffer_no_callback(): ...                  # 空 buffer 不调用回调
def test_stop_when_not_recording_does_not_raise(): ...    # 审查补充：未录音状态调用 stop 安全
```

---

## 依赖确认

写代码前在 conda voice 环境执行：

```bash
python -c "import noisereduce; import openwakeword; import funasr; print('all ok')"
```

缺失时：

```bash
pip install noisereduce openwakeword funasr
```

> funasr 安装较慢，可加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 镜像。

---

## 预期测试结果

Chunk 2 完成后全量测试：

```
tests/test_audio_preprocessor.py   3 passed
tests/test_wake_word_detector.py   5 passed   ← 审查后补充1个
tests/test_asr_engine.py           6 passed   ← 审查后补充1个
（+ Chunk 1 的 18 个）
= 32 passed total
```
