from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DEPS_ROOT = PROJECT_ROOT / "deps"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    return float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class ProjectConfig:
    project_root: Path = PROJECT_ROOT
    runtime_dir: Path = Path(_env("QWEN_RUNTIME_DIR", str(PROJECT_ROOT / "runtime")))

    ros_audio_topic: str = _env("QWEN_AUDIO_TOPIC", "/audio_msg")
    surf_wake_topic: str = _env("SURF_WAKE_TOPIC", "/wake_word_event")
    surf_vad_topic: str = _env("SURF_VAD_TOPIC", "/vad_state")
    surf_speaker_topic: str = _env("SURF_SPEAKER_TOPIC", "/speaker_id")
    include_speaker_context: bool = _env_bool("SURF_QWEN_INCLUDE_SPEAKER_CONTEXT", True)
    write_context_status: bool = _env_bool("SURF_QWEN_WRITE_CONTEXT_STATUS", True)
    filter_bad_asr: bool = _env_bool("SURF_QWEN_FILTER_BAD_ASR", True)
    min_asr_chars: int = _env_int("SURF_QWEN_MIN_ASR_CHARS", 2)
    min_audio_confidence: float = _env_float("SURF_QWEN_MIN_AUDIO_CONFIDENCE", 0.55)
    qwen_server_url: str = _env("QWEN_SERVER_URL", "http://127.0.0.1:8000/infer")
    request_timeout_sec: float = _env_float("QWEN_REQUEST_TIMEOUT_SEC", 15.0)
    wake_words: tuple[str, ...] = _env_list(
        "QWEN_WAKE_WORDS",
        ("你好小浦", "小浦"),
    )
    always_listen: bool = _env_bool("QWEN_ALWAYS_LISTEN", False)
    wake_ack_enable: bool = _env_bool("SURF_QWEN_WAKE_ACK_ENABLE", True)
    wake_ack_text: str = _env("SURF_QWEN_WAKE_ACK_TEXT", "你好")
    wake_ack_text_zh: str = _env("SURF_QWEN_WAKE_ACK_TEXT_ZH", "你好")
    wake_ack_text_en: str = _env("SURF_QWEN_WAKE_ACK_TEXT_EN", "hello")
    wake_ack_cooldown_sec: float = _env_float("SURF_QWEN_WAKE_ACK_COOLDOWN_SEC", 1.0)
    wake_ack_action_enable: bool = _env_bool("SURF_QWEN_WAKE_ACK_ACTION_ENABLE", True)
    wake_ack_action_id: int = _env_int("SURF_QWEN_WAKE_ACK_ACTION_ID", 25)
    wake_ack_action_label: str = _env("SURF_QWEN_WAKE_ACK_ACTION_LABEL", "面前挥手")
    thinking_ack_enable: bool = _env_bool("SURF_QWEN_THINKING_ACK_ENABLE", True)
    thinking_ack_text: str = _env("SURF_QWEN_THINKING_ACK_TEXT", "收到，我在思考")
    thinking_action_enable: bool = _env_bool("SURF_QWEN_THINKING_ACTION_ENABLE", False)
    wake_listen_sec: float = _env_float("SURF_QWEN_WAKE_LISTEN_SEC", 8.0)

    model_path: str = _env("QWEN_MODEL_PATH", str(DEPS_ROOT / "Qwen3.5-0.8B" / "model"))
    reply_backend: str = _env("QWEN_REPLY_BACKEND", "local")
    dashscope_model: str = _env("QWEN_DASHSCOPE_MODEL", "qwen-plus")
    dashscope_base_url: str = _env("QWEN_DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    rag_server_url: str = _env("QWEN_RAG_SERVER_URL", "http://127.0.0.1:8010/chat")
    server_host: str = _env("QWEN_SERVER_HOST", "0.0.0.0")
    server_port: int = _env_int("QWEN_SERVER_PORT", 8000)
    max_new_tokens: int = _env_int("QWEN_MAX_NEW_TOKENS", 50)
    temperature: float = _env_float("QWEN_TEMPERATURE", 0.7)

    unitree_domain_id: int = _env_int("UNITREE_DOMAIN_ID", 0)
    unitree_enable: bool = _env_bool("UNITREE_ENABLE", True)
    unitree_network_interface: str = _env("UNITREE_NETWORK_INTERFACE", "enp8s0")
    unitree_audio_volume: int = _env_int("UNITREE_AUDIO_VOLUME", 85)

    action_enable: bool = _env_bool("QWEN_ACTION_ENABLE", True)
    action_execute: bool = _env_bool("QWEN_ACTION_EXECUTE", True)
    action_backend: str = _env("QWEN_ACTION_BACKEND", "deepseek")
    action_threshold: float = _env_float("QWEN_ACTION_THRESHOLD", 0.8)
    action_auto_release: bool = _env_bool("QWEN_ACTION_AUTO_RELEASE", False)
    action_release_after_sec: float = _env_float("QWEN_ACTION_RELEASE_AFTER_SEC", 0.0)
    action_keyword_first: bool = _env_bool("QWEN_ACTION_KEYWORD_FIRST", True)
    action_python: str = _env(
        "QWEN_ACTION_PYTHON",
        str(DEPS_ROOT / "unitree_g1_action_classifier_package" / ".venv" / "bin" / "python"),
    )
    action_script: Path = Path(
        _env(
            "QWEN_ACTION_SCRIPT",
            str(DEPS_ROOT / "unitree_g1_action_classifier_package" / "arm_action_classifier" / "arm_action_classifier.py"),
        )
    )
    action_runner: Path = Path(
        _env(
            "QWEN_ACTION_RUNNER",
            str(DEPS_ROOT / "unitree_g1_action_classifier_package" / "unitree_sdk2" / "build" / "bin" / "g1_arm_action_example"),
        )
    )

    @property
    def tts_mp3_path(self) -> Path:
        return self.runtime_dir / "tts.mp3"

    @property
    def tts_wav_path(self) -> Path:
        return self.runtime_dir / "tts.wav"

    @property
    def wake_light_command_path(self) -> Path:
        return self.runtime_dir / "wake_light_command.json"

    @property
    def tts_play_context_path(self) -> Path:
        return self.runtime_dir / "tts_play_context.json"


CONFIG = ProjectConfig()
