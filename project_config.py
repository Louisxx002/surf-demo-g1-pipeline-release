from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DEPS_ROOT = PROJECT_ROOT / "deps"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_compat(name: str, legacy_name: str, default: str) -> str:
    return os.environ.get(name, os.environ.get(legacy_name, default))


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def _env_int_compat(name: str, legacy_name: str, default: int) -> int:
    value = os.environ.get(name, os.environ.get(legacy_name))
    if value is None:
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    return float(value)


def _env_float_compat(name: str, legacy_name: str, default: float) -> float:
    value = os.environ.get(name, os.environ.get(legacy_name))
    if value is None:
        return default
    return float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_bool_compat(name: str, legacy_name: str, default: bool) -> bool:
    value = os.environ.get(name, os.environ.get(legacy_name))
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_list_compat(name: str, legacy_name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name, os.environ.get(legacy_name))
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class ProjectConfig:
    project_root: Path = PROJECT_ROOT
    runtime_dir: Path = Path(_env_compat("LLM_RUNTIME_DIR", "QWEN_RUNTIME_DIR", str(PROJECT_ROOT / "runtime")))

    ros_audio_topic: str = _env_compat("LLM_AUDIO_TOPIC", "QWEN_AUDIO_TOPIC", "/audio_msg")
    surf_wake_topic: str = _env("SURF_WAKE_TOPIC", "/wake_word_event")
    surf_vad_topic: str = _env("SURF_VAD_TOPIC", "/vad_state")
    surf_speaker_topic: str = _env("SURF_SPEAKER_TOPIC", "/speaker_id")
    include_speaker_context: bool = _env_bool_compat("SURF_LLM_INCLUDE_SPEAKER_CONTEXT", "SURF_QWEN_INCLUDE_SPEAKER_CONTEXT", True)
    write_context_status: bool = _env_bool_compat("SURF_LLM_WRITE_CONTEXT_STATUS", "SURF_QWEN_WRITE_CONTEXT_STATUS", True)
    filter_bad_asr: bool = _env_bool_compat("SURF_LLM_FILTER_BAD_ASR", "SURF_QWEN_FILTER_BAD_ASR", True)
    min_asr_chars: int = _env_int_compat("SURF_LLM_MIN_ASR_CHARS", "SURF_QWEN_MIN_ASR_CHARS", 2)
    min_audio_confidence: float = _env_float_compat("SURF_LLM_MIN_AUDIO_CONFIDENCE", "SURF_QWEN_MIN_AUDIO_CONFIDENCE", 0.55)
    llm_server_url: str = _env_compat("LLM_SERVER_URL", "QWEN_SERVER_URL", "http://127.0.0.1:8000/infer")
    request_timeout_sec: float = _env_float_compat("LLM_REQUEST_TIMEOUT_SEC", "QWEN_REQUEST_TIMEOUT_SEC", 15.0)
    wake_words: tuple[str, ...] = _env_list(
        "LLM_WAKE_WORDS",
        _env_list(
            "QWEN_WAKE_WORDS",
            ("你好小浦", "小浦"),
        ),
    )
    always_listen: bool = _env_bool_compat("LLM_ALWAYS_LISTEN", "QWEN_ALWAYS_LISTEN", False)
    wake_ack_enable: bool = _env_bool_compat("SURF_LLM_WAKE_ACK_ENABLE", "SURF_QWEN_WAKE_ACK_ENABLE", True)
    wake_ack_text: str = _env_compat("SURF_LLM_WAKE_ACK_TEXT", "SURF_QWEN_WAKE_ACK_TEXT", "你好")
    wake_ack_text_zh: str = _env_compat("SURF_LLM_WAKE_ACK_TEXT_ZH", "SURF_QWEN_WAKE_ACK_TEXT_ZH", "你好")
    wake_ack_text_en: str = _env_compat("SURF_LLM_WAKE_ACK_TEXT_EN", "SURF_QWEN_WAKE_ACK_TEXT_EN", "hello")
    wake_ack_cooldown_sec: float = _env_float_compat("SURF_LLM_WAKE_ACK_COOLDOWN_SEC", "SURF_QWEN_WAKE_ACK_COOLDOWN_SEC", 1.0)
    wake_ack_action_enable: bool = _env_bool_compat("SURF_LLM_WAKE_ACK_ACTION_ENABLE", "SURF_QWEN_WAKE_ACK_ACTION_ENABLE", True)
    wake_ack_action_id: int = _env_int_compat("SURF_LLM_WAKE_ACK_ACTION_ID", "SURF_QWEN_WAKE_ACK_ACTION_ID", 25)
    wake_ack_action_label: str = _env_compat("SURF_LLM_WAKE_ACK_ACTION_LABEL", "SURF_QWEN_WAKE_ACK_ACTION_LABEL", "面前挥手")
    wake_ack_guard_sec: float = _env_float("LLM_WAKE_ACK_GUARD_SEC", 0.8)
    first_turn_strict_gate_enable: bool = _env_bool("LLM_FIRST_TURN_STRICT_GATE_ENABLE", True)
    first_turn_min_chars: int = _env_int("LLM_FIRST_TURN_MIN_CHARS", 2)
    first_turn_require_intent: bool = _env_bool("LLM_FIRST_TURN_REQUIRE_INTENT", False)
    first_turn_noise_texts: tuple[str, ...] = field(
        default_factory=lambda: _env_list(
            "LLM_FIRST_TURN_NOISE_TEXTS",
            ("我在", "我", "在", "嗯", "啊", "呃", "哦", "好", "好的", "你好", "小浦", "你好小浦", "存在", "准在"),
        )
    )
    thinking_ack_enable: bool = _env_bool_compat("SURF_LLM_THINKING_ACK_ENABLE", "SURF_QWEN_THINKING_ACK_ENABLE", True)
    thinking_ack_text: str = _env_compat("SURF_LLM_THINKING_ACK_TEXT", "SURF_QWEN_THINKING_ACK_TEXT", "小浦思考中")
    thinking_ack_skip_action_intent: bool = _env_bool("LLM_THINKING_ACK_SKIP_ACTION_INTENT", True)
    thinking_ack_play_gap_sec: float = _env_float("LLM_THINKING_ACK_PLAY_GAP_SEC", 0.6)
    thinking_action_enable: bool = _env_bool_compat("SURF_LLM_THINKING_ACTION_ENABLE", "SURF_QWEN_THINKING_ACTION_ENABLE", False)
    wake_listen_sec: float = _env_float_compat("SURF_LLM_WAKE_LISTEN_SEC", "SURF_QWEN_WAKE_LISTEN_SEC", 8.0)
    followup_enable: bool = _env_bool("LLM_FOLLOWUP_ENABLE", True)
    followup_timeout_sec: float = _env_float("LLM_FOLLOWUP_TIMEOUT_SEC", 8.0)
    followup_prompt_enable: bool = _env_bool("LLM_FOLLOWUP_PROMPT_ENABLE", True)
    followup_prompt_text: str = _env("LLM_FOLLOWUP_PROMPT_TEXT", "还有什么想问的吗？")
    reply_brief_enable: bool = _env_bool("LLM_REPLY_BRIEF_ENABLE", True)
    reply_max_chinese_chars: int = _env_int("LLM_REPLY_MAX_CHINESE_CHARS", 80)
    reply_brief_style: str = _env(
        "LLM_REPLY_BRIEF_STYLE",
        "默认简短回答，1-2句话；用户明确要求详细、展开、具体介绍、多讲一点时再适当展开。",
    )
    terminate_command_enable: bool = _env_bool("LLM_TERMINATE_COMMAND_ENABLE", True)
    terminate_commands: tuple[str, ...] = _env_list(
        "LLM_TERMINATE_COMMANDS",
        ("关闭交互", "结束交互", "退出交互"),
    )
    terminate_ack_text: str = _env("LLM_TERMINATE_ACK_TEXT", "好的，已关闭交互")
    standby_ack_enable: bool = _env_bool("LLM_STANDBY_ACK_ENABLE", True)
    standby_ack_text: str = _env("LLM_STANDBY_ACK_TEXT", "待机")
    tts_guard_enable: bool = _env_bool("LLM_TTS_GUARD_ENABLE", True)
    tts_guard_grace_sec: float = _env_float("LLM_TTS_GUARD_GRACE_SEC", 0.0)
    tts_playback_end_buffer_sec: float = _env_float("LLM_TTS_PLAYBACK_END_BUFFER_SEC", 0.3)
    self_speech_similarity_threshold: float = _env_float("LLM_SELF_SPEECH_SIMILARITY_THRESHOLD", 0.72)

    model_path: str = _env_compat("LLM_MODEL_PATH", "QWEN_MODEL_PATH", str(DEPS_ROOT / "Qwen3.5-0.8B" / "model"))
    reply_backend: str = _env_compat("LLM_REPLY_BACKEND", "QWEN_REPLY_BACKEND", "local")
    dashscope_model: str = _env_compat("LLM_DASHSCOPE_MODEL", "QWEN_DASHSCOPE_MODEL", "qwen-plus")
    dashscope_base_url: str = _env_compat("LLM_DASHSCOPE_BASE_URL", "QWEN_DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    deepseek_model: str = _env_compat("LLM_DEEPSEEK_MODEL", "QWEN_DEEPSEEK_MODEL", _env("CHAT_MODEL", "deepseek-v4-pro"))
    deepseek_base_url: str = _env_compat("LLM_DEEPSEEK_BASE_URL", "QWEN_DEEPSEEK_BASE_URL", _env("OPENAI_BASE_URL", "https://api.deepseek.com"))
    rag_server_url: str = _env_compat("LLM_RAG_SERVER_URL", "QWEN_RAG_SERVER_URL", "http://127.0.0.1:8010/chat")
    server_host: str = _env_compat("LLM_SERVER_HOST", "QWEN_SERVER_HOST", "0.0.0.0")
    server_port: int = _env_int_compat("LLM_SERVER_PORT", "QWEN_SERVER_PORT", 8000)
    max_new_tokens: int = _env_int_compat("LLM_MAX_NEW_TOKENS", "QWEN_MAX_NEW_TOKENS", 50)
    temperature: float = _env_float_compat("LLM_TEMPERATURE", "QWEN_TEMPERATURE", 0.7)

    unitree_domain_id: int = _env_int("UNITREE_DOMAIN_ID", 0)
    unitree_enable: bool = _env_bool("UNITREE_ENABLE", True)
    unitree_network_interface: str = _env("UNITREE_NETWORK_INTERFACE", "enp8s0")
    unitree_audio_volume: int = _env_int("UNITREE_AUDIO_VOLUME", 85)

    robot_skill_enable: bool = _env_bool("LLM_ROBOT_SKILL_ENABLE", True)
    robot_skill_execute: bool = _env_bool("LLM_ROBOT_SKILL_EXECUTE", True)
    robot_skill_runner: Path = Path(
        _env("LLM_ROBOT_SKILL_RUNNER", str(PROJECT_ROOT / "scripts" / "g1_robot_skill_command.py"))
    )
    robot_skill_ack_enable: bool = _env_bool("LLM_ROBOT_SKILL_ACK_ENABLE", True)
    robot_skill_song_file: Path = Path(
        _env("LLM_ROBOT_SKILL_SONG_FILE", str(runtime_dir / "songs" / "song_1.wav"))
    )
    robot_skill_sing_fallback_text: str = _env("LLM_ROBOT_SKILL_SING_FALLBACK_TEXT", "啦啦啦，小浦给你唱一首歌。")
    locomotion_max_vx: float = _env_float("LLM_LOCOMOTION_MAX_VX", 0.2)
    locomotion_max_vy: float = _env_float("LLM_LOCOMOTION_MAX_VY", 0.1)
    locomotion_max_yaw: float = _env_float("LLM_LOCOMOTION_MAX_YAW", 0.4)
    locomotion_max_duration_sec: float = _env_float("LLM_LOCOMOTION_MAX_DURATION_SEC", 0.8)

    action_enable: bool = _env_bool_compat("LLM_ACTION_ENABLE", "QWEN_ACTION_ENABLE", True)
    action_execute: bool = _env_bool_compat("LLM_ACTION_EXECUTE", "QWEN_ACTION_EXECUTE", True)
    action_backend: str = _env_compat("LLM_ACTION_BACKEND", "QWEN_ACTION_BACKEND", "deepseek")
    action_threshold: float = _env_float_compat("LLM_ACTION_THRESHOLD", "QWEN_ACTION_THRESHOLD", 0.8)
    action_auto_release: bool = _env_bool_compat("LLM_ACTION_AUTO_RELEASE", "QWEN_ACTION_AUTO_RELEASE", False)
    action_release_after_sec: float = _env_float_compat("LLM_ACTION_RELEASE_AFTER_SEC", "QWEN_ACTION_RELEASE_AFTER_SEC", 0.0)
    action_keyword_first: bool = _env_bool_compat("LLM_ACTION_KEYWORD_FIRST", "QWEN_ACTION_KEYWORD_FIRST", True)
    action_python: str = _env_compat(
        "LLM_ACTION_PYTHON",
        "QWEN_ACTION_PYTHON",
        str(DEPS_ROOT / "unitree_g1_action_classifier_package" / ".venv" / "bin" / "python"),
    )
    action_script: Path = Path(
        _env_compat(
            "LLM_ACTION_SCRIPT",
            "QWEN_ACTION_SCRIPT",
            str(DEPS_ROOT / "unitree_g1_action_classifier_package" / "arm_action_classifier" / "arm_action_classifier.py"),
        )
    )
    action_runner: Path = Path(
        _env_compat(
            "LLM_ACTION_RUNNER",
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
    def followup_control_path(self) -> Path:
        return Path(_env("LLM_FOLLOWUP_CONTROL_FILE", str(self.runtime_dir / "followup_control.json")))

    @property
    def standby_ack_event_path(self) -> Path:
        return Path(_env("LLM_STANDBY_ACK_EVENT_FILE", str(self.runtime_dir / "standby_ack_event.json")))

    @property
    def tts_guard_path(self) -> Path:
        return Path(_env("LLM_TTS_GUARD_FILE", str(self.runtime_dir / "tts_guard.json")))

    @property
    def tts_play_context_path(self) -> Path:
        return self.runtime_dir / "tts_play_context.json"


CONFIG = ProjectConfig()
