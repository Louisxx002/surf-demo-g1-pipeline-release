from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import noisereduce as nr

from config.voice_config import CONFIG


class AudioPreprocessor(ABC):
    """音频前处理抽象接口，支持降噪和 AEC 远端参考。"""

    @abstractmethod
    def process(self, raw_pcm: bytes) -> bytes: ...

    def on_far_end(self, ref_pcm: bytes) -> None:
        pass


class NoiseReduceProcessor(AudioPreprocessor):
    """noisereduce 稳态降噪，适合空调/风扇背景噪声。"""

    def __init__(self, sample_rate: int = CONFIG.sample_rate) -> None:
        self._sample_rate = sample_rate

    def process(self, raw_pcm: bytes) -> bytes:
        audio = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
        reduced = nr.reduce_noise(y=audio, sr=self._sample_rate, stationary=True)
        return reduced.astype(np.int16).tobytes()
