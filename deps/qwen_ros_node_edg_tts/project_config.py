from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


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
    qwen_server_url: str = _env("QWEN_SERVER_URL", "http://127.0.0.1:8000/infer")
    request_timeout_sec: float = _env_float("QWEN_REQUEST_TIMEOUT_SEC", 15.0)
    wake_words: tuple[str, ...] = _env_list("QWEN_WAKE_WORDS", ("西浦小g", "小g", "小G"))
    always_listen: bool = _env_bool("QWEN_ALWAYS_LISTEN", False)

    model_path: str = _env("QWEN_MODEL_PATH", "/home/louisxx/Qwen3.5-0.8B/model")
    server_host: str = _env("QWEN_SERVER_HOST", "0.0.0.0")
    server_port: int = _env_int("QWEN_SERVER_PORT", 8000)
    max_new_tokens: int = _env_int("QWEN_MAX_NEW_TOKENS", 50)
    temperature: float = _env_float("QWEN_TEMPERATURE", 0.7)

    unitree_domain_id: int = _env_int("UNITREE_DOMAIN_ID", 0)
    unitree_network_interface: str = _env("UNITREE_NETWORK_INTERFACE", "enp8s0")
    unitree_audio_volume: int = _env_int("UNITREE_AUDIO_VOLUME", 85)

    action_enable: bool = _env_bool("QWEN_ACTION_ENABLE", True)
    action_execute: bool = _env_bool("QWEN_ACTION_EXECUTE", True)
    action_backend: str = _env("QWEN_ACTION_BACKEND", "qwen")
    action_threshold: float = _env_float("QWEN_ACTION_THRESHOLD", 0.8)
    action_auto_release: bool = _env_bool("QWEN_ACTION_AUTO_RELEASE", False)
    action_python: str = _env(
        "QWEN_ACTION_PYTHON",
        "/home/louisxx/unitree_g1_action_classifier_package/.venv/bin/python",
    )
    action_script: Path = Path(
        _env(
            "QWEN_ACTION_SCRIPT",
            "/home/louisxx/unitree_g1_action_classifier_package/arm_action_classifier/arm_action_classifier.py",
        )
    )
    action_runner: Path = Path(
        _env(
            "QWEN_ACTION_RUNNER",
            "/home/louisxx/unitree_g1_action_classifier_package/unitree_sdk2/build/bin/g1_arm_action_example",
        )
    )

    @property
    def tts_mp3_path(self) -> Path:
        return self.runtime_dir / "tts.mp3"

    @property
    def tts_wav_path(self) -> Path:
        return self.runtime_dir / "tts.wav"


CONFIG = ProjectConfig()
