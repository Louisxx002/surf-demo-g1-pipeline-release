from wav import read_wav, play_pcm_stream
from collections import deque
import hashlib
import json
from pathlib import Path
import threading
import time

from pipeline_log.pipeline_logger import PipelineLogger
from project_config import CONFIG

CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)
_pipeline_logger = PipelineLogger()
_current_session = None
_light_lock = threading.Lock()
_light_state = {"color": "idle", "red": 0, "green": 0, "blue": 0, "effect": "solid"}
NON_REPLY_KINDS = ("wake_ack", "thinking_ack", "system_ack")
played_ids = deque(maxlen=20)
played_id_set = set()


class DirectUnitreeBackend:
    def __init__(self) -> None:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient

        ChannelFactoryInitialize(CONFIG.unitree_domain_id, CONFIG.unitree_network_interface)
        self.audio_client = AudioClient()
        self.audio_client.SetTimeout(10.0)
        self.audio_client.Init()
        self.audio_client.SetVolume(CONFIG.unitree_audio_volume)

    def led_control(self, red: int, green: int, blue: int) -> object:
        return self.audio_client.LedControl(red, green, blue)

    def play(self, wav_path: Path, text: str, stream_name: str = "tts") -> bool:
        pcm_list, _sample_rate, _num_channels, is_ok = read_wav(str(wav_path))
        if not is_ok:
            return False
        play_pcm_stream(self.audio_client, pcm_list, stream_name)
        return True


class RelayUnitreeBackend:
    def __init__(self) -> None:
        from robot_relay.robot_relay_client import RobotRelayClient

        self.client = RobotRelayClient(
            CONFIG.robot_relay_host,
            CONFIG.robot_relay_port,
            timeout_sec=CONFIG.robot_relay_timeout_sec,
        )
        response = self.client.health()
        print(f"Robot relay health ok: {response}", flush=True)

    def led_control(self, red: int, green: int, blue: int) -> object:
        response = self.client.set_light(red, green, blue)
        return response.get("ret", 0)

    def play(self, wav_path: Path, text: str, stream_name: str = "tts") -> bool:
        response = self.client.play_wav(str(wav_path), stream_name)
        print(f"relay played wav stream={stream_name}: {response}", flush=True)
        return True


def _create_backend():
    backend = CONFIG.unitree_backend.strip().lower()
    if backend == "relay":
        print(
            f"Unitree Audio Player using relay backend {CONFIG.robot_relay_host}:{CONFIG.robot_relay_port}",
            flush=True,
        )
        return RelayUnitreeBackend()
    if backend == "direct":
        print(
            f"Unitree Audio Player using direct backend if={CONFIG.unitree_network_interface} domain={CONFIG.unitree_domain_id}",
            flush=True,
        )
        return DirectUnitreeBackend()
    raise ValueError(f"unsupported UNITREE_BACKEND={CONFIG.unitree_backend!r}; expected direct or relay")


def _remember_play_id(play_id: str) -> None:
    if len(played_ids) == played_ids.maxlen:
        old_play_id = played_ids.popleft()
        played_id_set.discard(old_play_id)
    played_ids.append(play_id)
    played_id_set.add(play_id)


def _build_play_id(kind: str, session_id: str, text: str, context_updated_at: float, wav_mtime: float) -> str:
    source = {
        "kind": kind or "",
        "session_id": session_id or "",
        "text": text or "",
        "updated_at": context_updated_at or wav_mtime,
    }
    raw = json.dumps(source, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _wav_duration_sec(path: Path) -> float:
    import wave

    try:
        with wave.open(str(path), "rb") as wf:
            rate = float(wf.getframerate() or 1)
            frames = float(wf.getnframes() or 0)
            return frames / rate
    except Exception as exc:
        print(f"failed to read wav duration: {exc}", flush=True)
        return 0.0


def _write_followup_control(session_id: str, reason: str) -> None:
    if not CONFIG.followup_enable or not session_id:
        return
    try:
        CONFIG.followup_control_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "command": "open",
            "session_id": session_id,
            "timeout_sec": CONFIG.followup_timeout_sec,
            "reason": reason,
            "updated_at": time.time(),
        }
        CONFIG.followup_control_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"followup_control written reason={reason} session={session_id}", flush=True)
    except Exception as exc:
        print(f"follow-up control write failed: {exc}", flush=True)


def _write_tts_guard(
    active: bool,
    kind: str,
    text: str,
    session_id: str,
    extra_fields: dict[str, object] | None = None,
) -> None:
    if not CONFIG.tts_guard_enable:
        return
    try:
        CONFIG.tts_guard_path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        payload = {
            "active": active,
            "kind": kind,
            "text": text,
            "session_id": session_id,
            "updated_at": now,
        }
        if extra_fields:
            payload.update(extra_fields)
        if active:
            payload["started_at"] = now
            print(f"tts guard active written kind={kind} session={session_id}", flush=True)
        else:
            guard_until = float(payload.get("guard_until", now + CONFIG.tts_guard_grace_sec))
            payload["ended_at"] = now
            payload["guard_until"] = guard_until
            print(f"tts guard inactive written kind={kind} guard_until={guard_until:.3f}", flush=True)
        CONFIG.tts_guard_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"tts guard write failed: {exc}", flush=True)


def _set_light(color: str, red: int, green: int, blue: int, effect: str = "solid") -> None:
    with _light_lock:
        _light_state.update({"color": color, "red": red, "green": green, "blue": blue, "effect": effect})
    ret = audio_backend.led_control(red, green, blue)
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
                    audio_backend.led_control(0, 0, 0)
                else:
                    audio_backend.led_control(red, green, blue)
            except Exception as exc:
                print(f"wake light refresh failed: {exc}", flush=True)
        time.sleep(0.5)

if not CONFIG.unitree_enable:
    print("Unitree Audio Player disabled; UNITREE_ENABLE=0.")
    while True:
        time.sleep(3600)

audio_backend = _create_backend()

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
    play_context_updated_at = 0.0
    if CONFIG.tts_play_context_path.exists():
        current_play_context_mtime = CONFIG.tts_play_context_path.stat().st_mtime
        if current_play_context_mtime != last_play_context_mtime:
            last_play_context_mtime = current_play_context_mtime
        try:
            payload = json.loads(CONFIG.tts_play_context_path.read_text(encoding="utf-8"))
            play_kind = str(payload.get("kind", "reply"))
            play_session_id = str(payload.get("session_id", "")).strip()
            play_text = str(payload.get("text", ""))
            try:
                play_context_updated_at = float(payload.get("updated_at", 0.0))
            except (TypeError, ValueError):
                play_context_updated_at = 0.0
        except Exception:
            play_kind = "reply"
            play_context_updated_at = 0.0

    if CONFIG.tts_wav_path.exists():
        current_mtime = CONFIG.tts_wav_path.stat().st_mtime

        # 只有文件更新才播放
        if current_mtime != last_mtime:
            last_mtime = current_mtime
            play_id = _build_play_id(
                play_kind,
                play_session_id,
                play_text,
                play_context_updated_at,
                current_mtime,
            )
            if play_id in played_id_set:
                print(
                    f"duplicated tts play skipped play_id={play_id} kind={play_kind} session_id={play_session_id}",
                    flush=True,
                )
                time.sleep(0.2)
                continue
            _remember_play_id(play_id)

            play_started_at = time.time()
            wav_duration_sec = _wav_duration_sec(CONFIG.tts_wav_path)
            estimated_audio_end_at = play_started_at + wav_duration_sec
            safe_audio_end_at = estimated_audio_end_at + CONFIG.tts_playback_end_buffer_sec
            print(
                "tts playback timing kind=%s duration=%.2fs estimated_end=%.3f safe_end=%.3f"
                % (play_kind, wav_duration_sec, estimated_audio_end_at, safe_audio_end_at),
                flush=True,
            )

            if play_session_id:
                _current_session = _pipeline_logger.attach_session(play_session_id)
                _current_session.record(
                    "tts_play_started",
                    kind=play_kind,
                    text=play_text,
                    wav=str(CONFIG.tts_wav_path),
                )
                if play_kind not in NON_REPLY_KINDS:
                    _set_light("blue", 0, 0, 255)
                    print("reply playback started -> blue", flush=True)

            _write_tts_guard(True, play_kind, play_text, play_session_id)
            try:
                played = audio_backend.play(CONFIG.tts_wav_path, play_text, "tts")
                if played:
                    print("played audio", flush=True)
                else:
                    print("audio playback skipped or failed", flush=True)
            finally:
                remaining = safe_audio_end_at - time.time()
                if remaining > 0:
                    print(f"waiting for estimated audio end remaining={remaining:.2f}s", flush=True)
                    time.sleep(remaining)
                ended_at = time.time()
                guard_until = ended_at + CONFIG.tts_guard_grace_sec
                _write_tts_guard(
                    False,
                    play_kind,
                    play_text,
                    play_session_id,
                    extra_fields={
                        "ended_at": ended_at,
                        "wav_duration_sec": wav_duration_sec,
                        "estimated_audio_end_at": estimated_audio_end_at,
                        "safe_audio_end_at": safe_audio_end_at,
                        "guard_until": guard_until,
                        "updated_at": ended_at,
                    },
                )
                if play_session_id and _current_session is not None:
                    _current_session.record(
                        "tts_play_finished",
                        kind=play_kind,
                        text=play_text,
                        wav=str(CONFIG.tts_wav_path),
                    )
                if play_kind not in NON_REPLY_KINDS:
                    remaining_guard = guard_until - time.time()
                    if remaining_guard > 0:
                        print(
                            f"waiting tts guard grace before follow-up open remaining={remaining_guard:.2f}s",
                            flush=True,
                        )
                        time.sleep(remaining_guard)
                    _set_light("blue", 0, 0, 255)
                    print("reply playback finished -> blue", flush=True)
                    _write_followup_control(play_session_id, "reply_play_finished")

    time.sleep(0.2)  # 降低CPU占用
