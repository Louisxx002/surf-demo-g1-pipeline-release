from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
from wav import read_wav, play_pcm_stream
import json
import threading
import time

from pipeline_log.pipeline_logger import PipelineLogger
from project_config import CONFIG

CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)
_pipeline_logger = PipelineLogger()
_current_session = None
_light_lock = threading.Lock()
_light_state = {"color": "idle", "red": 0, "green": 0, "blue": 0, "effect": "solid"}


def _set_light(color: str, red: int, green: int, blue: int, effect: str = "solid") -> None:
    with _light_lock:
        _light_state.update({"color": color, "red": red, "green": green, "blue": blue, "effect": effect})
    ret = audio_client.LedControl(red, green, blue)
    print(f"wake light {color}: rgb=({red},{green},{blue}) effect={effect} ret={ret}", flush=True)


def _refresh_light_loop() -> None:
    while True:
        with _light_lock:
            color = _light_state["color"]
            red = _light_state["red"]
            green = _light_state["green"]
            blue = _light_state["blue"]
            effect = _light_state.get("effect", "solid")
        if color != "idle":
            try:
                if effect == "blink" and int(time.monotonic() * 2) % 2:
                    audio_client.LedControl(0, 0, 0)
                else:
                    audio_client.LedControl(red, green, blue)
            except Exception as exc:
                print(f"wake light refresh failed: {exc}", flush=True)
        time.sleep(0.5)

if not CONFIG.unitree_enable:
    print("Unitree Audio Player disabled; UNITREE_ENABLE=0.")
    while True:
        time.sleep(3600)

ChannelFactoryInitialize(CONFIG.unitree_domain_id, CONFIG.unitree_network_interface)

audio_client = AudioClient()
audio_client.SetTimeout(10.0)
audio_client.Init()
audio_client.SetVolume(CONFIG.unitree_audio_volume)

threading.Thread(target=_refresh_light_loop, daemon=True).start()

print("Unitree Audio Player started...", flush=True)
print(f"Watching wav file: {CONFIG.tts_wav_path}", flush=True)
print(f"Watching wake light command file: {CONFIG.wake_light_command_path}", flush=True)

last_mtime = CONFIG.tts_wav_path.stat().st_mtime if CONFIG.tts_wav_path.exists() else 0
last_light_mtime = CONFIG.wake_light_command_path.stat().st_mtime if CONFIG.wake_light_command_path.exists() else 0
last_play_context_mtime = CONFIG.tts_play_context_path.stat().st_mtime if CONFIG.tts_play_context_path.exists() else 0

if last_mtime:
    print("Existing tts.wav detected at startup, skipping old audio until a new file is generated.", flush=True)

while True:
    if CONFIG.wake_light_command_path.exists():
        current_light_mtime = CONFIG.wake_light_command_path.stat().st_mtime
        if current_light_mtime != last_light_mtime:
            last_light_mtime = current_light_mtime
            try:
                payload = json.loads(CONFIG.wake_light_command_path.read_text(encoding="utf-8"))
                color = str(payload.get("color", "unknown"))
                red = int(payload.get("red", 0))
                green = int(payload.get("green", 0))
                blue = int(payload.get("blue", 0))
                effect = str(payload.get("effect", "solid"))
                _set_light(color, red, green, blue, effect=effect)
            except Exception as exc:
                print(f"wake light command failed: {exc}", flush=True)
    play_kind = "reply"
    play_session_id = ""
    play_text = ""
    if CONFIG.tts_play_context_path.exists():
        current_play_context_mtime = CONFIG.tts_play_context_path.stat().st_mtime
        if current_play_context_mtime != last_play_context_mtime:
            last_play_context_mtime = current_play_context_mtime
        try:
            payload = json.loads(CONFIG.tts_play_context_path.read_text(encoding="utf-8"))
            play_kind = str(payload.get("kind", "reply"))
            play_session_id = str(payload.get("session_id", "")).strip()
            play_text = str(payload.get("text", ""))
        except Exception:
            play_kind = "reply"

    if CONFIG.tts_wav_path.exists():
        current_mtime = CONFIG.tts_wav_path.stat().st_mtime

        # 只有文件更新才播放
        if current_mtime != last_mtime:
            last_mtime = current_mtime

            if play_session_id:
                _current_session = _pipeline_logger.attach_session(play_session_id)
                _current_session.record(
                    "tts_play_started",
                    kind=play_kind,
                    text=play_text,
                    wav=str(CONFIG.tts_wav_path),
                )
                if play_kind not in ("wake_ack", "thinking_ack"):
                    _set_light("blue", 0, 0, 255)

            pcm_list, sample_rate, num_channels, is_ok = read_wav(str(CONFIG.tts_wav_path))

            if is_ok:
                play_pcm_stream(audio_client, pcm_list, "tts")
                print("played audio", flush=True)
                if play_session_id and _current_session is not None:
                    _current_session.record(
                        "tts_play_finished",
                        kind=play_kind,
                        text=play_text,
                        wav=str(CONFIG.tts_wav_path),
                    )
                if play_kind not in ("wake_ack", "thinking_ack"):
                    _set_light("blue", 0, 0, 255)

    time.sleep(0.2)  # 降低CPU占用
