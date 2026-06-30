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


def _env_int_opt(name: str) -> int | None:
    v = os.environ.get(name)
    return int(v) if v is not None else None


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    v = os.environ.get(name)
    if not v:
        return default
    return tuple(s.strip() for s in v.split(",") if s.strip())


@dataclass(frozen=True)
class VoiceConfig:
    sample_rate: int            = _env_int("VOICE_SAMPLE_RATE", 16000)
    channels: int               = _env_int("VOICE_CHANNELS", 1)
    frame_ms: int               = _env_int("VOICE_FRAME_MS", 20)
    bus_buffer_sec: float       = _env_float("VOICE_BUS_BUFFER_SEC", 1.0)

    mic_device: int | None      = _env_int_opt("VOICE_MIC_DEVICE")

    audio_source: str           = _env("VOICE_AUDIO_SOURCE", "local")
    robot_mic_group: str        = _env("VOICE_ROBOT_MIC_GROUP", "239.168.123.161")
    robot_mic_port: int         = _env_int("VOICE_ROBOT_MIC_PORT", 5555)
    robot_mic_interface: str    = _env("VOICE_ROBOT_MIC_IF", "192.168.123.225")

    wake_words: tuple[str, ...] = _env_list("VOICE_WAKE_WORDS", ("hey jarvis", "alexa"))
    wake_threshold: float       = _env_float("VOICE_WAKE_THRESHOLD", 0.5)
    wake_word_lang: str         = _env("VOICE_WAKE_WORD_LANG", "zh")
    kws_model_dir: str          = _env("VOICE_KWS_MODEL_DIR",
                                        str(PROJECT_ROOT / "models" / "kws"))
    wakeup_dedup_sec: float     = _env_float("VOICE_WAKEUP_DEDUP_SEC", 0.5)

    vad_silence_frames: int     = _env_int("VOICE_VAD_SILENCE_FRAMES", 30)

    asr_model: str              = _env(
        "VOICE_ASR_MODEL",
        str(Path.home() / ".cache" / "modelscope" / "hub" / "models" / "iic" / "speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"),
    )
    asr_vad_model: str          = _env("VOICE_ASR_VAD_MODEL", "")
    asr_vad_max_single_segment_time: int = _env_int(
        "VOICE_ASR_VAD_MAX_SINGLE_SEGMENT_TIME",
        30000,
    )
    asr_window_sec: float       = _env_float("VOICE_ASR_WINDOW_SEC", 8.0)

    voiceprint_capture_sec: float  = _env_float("VOICE_VOICEPRINT_SEC", 3.5)
    voiceprint_model: str          = _env("VOICE_VOICEPRINT_MODEL",
                                          "pyannote/wespeaker-voxceleb-resnet34-LM")
    speaker_sim_threshold: float   = _env_float("VOICE_SPEAKER_SIM_THRESHOLD", 0.50)
    speaker_max_history: int       = _env_int("VOICE_SPEAKER_MAX_HISTORY", 20)
    vad_holdoff_sec: float         = _env_float("VOICE_VAD_HOLDOFF_SEC", 4.0)

    ros_audio_topic: str        = _env("VOICE_ROS_AUDIO_TOPIC", "/audio_msg")
    ros_direction_topic: str    = _env("VOICE_ROS_DIRECTION_TOPIC", "/voice_direction")
    ros_wake_topic: str         = _env("VOICE_ROS_WAKE_TOPIC", "/wake_word_event")
    ros_vad_topic: str          = _env("VOICE_ROS_VAD_TOPIC", "/vad_state")
    ros_speaker_topic: str      = _env("VOICE_ROS_SPEAKER_TOPIC", "/speaker_id")

    unitree_domain_id: int      = _env_int("UNITREE_DOMAIN_ID", 0)
    unitree_network_interface: str = _env("UNITREE_NETWORK_INTERFACE", "enp8s0")

    @property
    def frame_bytes(self) -> int:
        """Exact PCM byte length for one VAD frame (16-bit mono)."""
        return int(self.sample_rate * self.frame_ms / 1000) * 2


CONFIG = VoiceConfig()
