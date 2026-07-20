from __future__ import annotations

import json
import importlib
import threading
import sys
from types import ModuleType, SimpleNamespace

from pipeline_log.pipeline_logger import SessionLog
from turn_detection.runtime_shadow import TurnShadowRuntime


def _stub_module(monkeypatch, name: str, symbol: str) -> None:
    package_name = name.split(".", 1)[0]
    monkeypatch.setitem(sys.modules, package_name, ModuleType(package_name))
    module = ModuleType(name)
    setattr(module, symbol, type(symbol, (), {}))
    monkeypatch.setitem(sys.modules, name, module)


def _load_voice_runtime(monkeypatch):
    dependencies = {
        "asr.asr_engine": "ASREngine",
        "audio.audio_bus": "AudioBus",
        "audio.mic_capture": "MicCapture",
        "vad.vad_engine": "VADEngine",
        "voice_id.speaker_database": "SpeakerDatabase",
        "voice_id.voiceprint_recognizer": "VoiceprintRecognizer",
        "wake_word.chinese_wake_word_detector": "ChineseWakeWordDetector",
        "wake_word.wake_word_detector": "WakeWordDetector",
        "wake_word.wakeup_dispatcher": "WakeupDispatcher",
    }
    for module_name, symbol in dependencies.items():
        _stub_module(monkeypatch, module_name, symbol)
    config_module = ModuleType("config.voice_config")
    config_module.CONFIG = SimpleNamespace(
        asr_max_recording_sec=10.0,
        vad_holdoff_sec=0.0,
    )
    monkeypatch.setitem(sys.modules, "config.voice_config", config_module)
    monkeypatch.delitem(sys.modules, "surf_voice_runtime", raising=False)
    return importlib.import_module("surf_voice_runtime").SurfVoiceRuntime


class RecordingSink:
    def __init__(self) -> None:
        self.events = []

    def publish(self, topic, msg_type, data) -> None:
        self.events.append((topic, msg_type, data))


class RecordingShadow:
    def __init__(self) -> None:
        self.events = []

    def submit_vad(self, is_speech: bool, *, agent_playing: bool) -> None:
        self.events.append(("vad", is_speech, agent_playing))

    def submit_wake(self, word: str, *, agent_playing: bool) -> None:
        self.events.append(("wake", word, agent_playing))

    def submit_asr_final(self, text: str, *, agent_playing: bool) -> None:
        self.events.append(("asr_final", text, agent_playing))


class FakeASR:
    def start_recording(self, *, initial_audio: bytes) -> None:
        self.initial_audio = initial_audio


class FakeVoiceprint:
    def start_capture(self, *, initial_audio: bytes) -> None:
        self.initial_audio = initial_audio


class ClosingShadow:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_disabled_runtime_does_not_create_shadow_log(tmp_path) -> None:
    session_log = SessionLog(session_id="session-001", session_dir=tmp_path)

    runtime = TurnShadowRuntime(session_log=session_log, enabled=False)
    runtime.submit_wake("hello")
    runtime.submit_vad(True, agent_playing=False)
    runtime.submit_asr_final("hello there", agent_playing=False)
    runtime.submit_agent_playing(True)
    runtime.close()

    assert not (tmp_path / "turn_shadow.jsonl").exists()


def test_enabled_runtime_writes_both_detector_decisions(tmp_path) -> None:
    session_log = SessionLog(session_id="session-001", session_dir=tmp_path)
    runtime = TurnShadowRuntime(session_log=session_log, enabled=True)

    runtime.submit_wake("hello")
    runtime.close()

    lines = (tmp_path / "turn_shadow.jsonl").read_text(encoding="utf-8").splitlines()
    decisions = [json.loads(line) for line in lines]
    assert [decision["detector_name"] for decision in decisions] == [
        "baseline",
        "dynamic_v1",
    ]
    assert len({decision["event_id"] for decision in decisions}) == 2
    assert all(decision["session_id"] == "session-001" for decision in decisions)
    assert all(decision["turn_id"] == "turn-001" for decision in decisions)


def test_voice_runtime_mirrors_vad_without_changing_publish_path(monkeypatch) -> None:
    SurfVoiceRuntime = _load_voice_runtime(monkeypatch)
    runtime = object.__new__(SurfVoiceRuntime)
    runtime._sink = RecordingSink()
    runtime._turn_shadow = RecordingShadow()
    runtime._recording = True
    guard_calls = []

    def agent_playing() -> bool:
        guard_calls.append(True)
        return True

    runtime._is_tts_guard_active = agent_playing

    runtime._on_vad(True)

    assert runtime._sink.events == [("/vad_state", "bool", True)]
    assert guard_calls == []
    assert runtime._turn_shadow.events[0][:2] == ("vad", True)
    assert runtime._turn_shadow.events[0][2] is agent_playing


def test_voice_runtime_mirrors_wake_after_session_creation(monkeypatch) -> None:
    SurfVoiceRuntime = _load_voice_runtime(monkeypatch)
    runtime = object.__new__(SurfVoiceRuntime)
    runtime._sink = RecordingSink()
    runtime._turn_shadow = RecordingShadow()
    runtime._close_followup_window = lambda _reason: None
    runtime._new_session = lambda _word: "session-001"
    agent_playing = lambda: True
    runtime._is_tts_guard_active = agent_playing
    runtime._bus = SimpleNamespace(get_buffer=lambda: [])
    runtime._asr_preroll = lambda _snapshot: []
    runtime._asr = FakeASR()
    runtime._vprint = FakeVoiceprint()
    runtime._arm_asr_max_recording_deadline = lambda: None
    runtime._session_log = None

    runtime._on_wake("hello")

    assert runtime._turn_shadow.events == [("wake", "hello", agent_playing)]
    assert runtime._recording is True
    assert runtime._sink.events[0][0] == "/wake_word_event"


def test_voice_runtime_mirrors_final_asr_text(monkeypatch) -> None:
    SurfVoiceRuntime = _load_voice_runtime(monkeypatch)
    runtime = object.__new__(SurfVoiceRuntime)
    runtime._sink = RecordingSink()
    runtime._turn_shadow = RecordingShadow()
    agent_playing = lambda: False
    runtime._is_tts_guard_active = agent_playing
    runtime._current_speaker = "speaker-001"
    runtime._session_id = "session-001"
    runtime._session_log = None

    runtime._on_asr("hello there")

    assert runtime._turn_shadow.events == [
        ("asr_final", "hello there", agent_playing)
    ]
    assert runtime._sink.events[0][0] == "/audio_msg"


def test_new_session_replaces_shadow_runtime_with_session_log(monkeypatch, tmp_path) -> None:
    SurfVoiceRuntime = _load_voice_runtime(monkeypatch)
    module = sys.modules["surf_voice_runtime"]
    monkeypatch.setenv("TURN_SHADOW_ENABLE", "1")
    session_log = SessionLog(session_id="session-001", session_dir=tmp_path)
    created = []

    def create_shadow(*, session_log, enabled):
        created.append((session_log, enabled))
        return RecordingShadow()

    monkeypatch.setattr(module, "TurnShadowRuntime", create_shadow)
    runtime = object.__new__(SurfVoiceRuntime)
    previous = ClosingShadow()
    runtime._turn_shadow = previous
    runtime._pipeline_logger = SimpleNamespace(
        start_session=lambda _wake_word: session_log
    )

    assert runtime._new_session("hello") == "session-001"

    assert previous.closed is True
    assert created == [(session_log, True)]
    assert isinstance(runtime._turn_shadow, RecordingShadow)


def test_worker_continues_when_one_detector_fails_to_initialize(
    monkeypatch, tmp_path
) -> None:
    runtime_module = importlib.import_module("turn_detection.runtime_shadow")

    def broken_detector():
        raise RuntimeError("detector unavailable")

    monkeypatch.setattr(runtime_module, "BaselineDetector", broken_detector)
    session_log = SessionLog(session_id="session-001", session_dir=tmp_path)
    runtime = TurnShadowRuntime(session_log=session_log, enabled=True)

    runtime.submit_wake("hello")
    runtime.close()

    lines = (tmp_path / "turn_shadow.jsonl").read_text(encoding="utf-8").splitlines()
    decisions = [json.loads(line) for line in lines]
    assert [decision["detector_name"] for decision in decisions] == ["dynamic_v1"]


def test_vad_submission_never_waits_for_event_id_lock(tmp_path) -> None:
    session_log = SessionLog(session_id="session-001", session_dir=tmp_path)
    runtime = TurnShadowRuntime(session_log=session_log, enabled=False)
    runtime._enabled = True
    contended_lock = threading.Lock()
    contended_lock.acquire()
    runtime._sequence_lock = contended_lock
    submitter = threading.Thread(
        target=runtime.submit_vad,
        args=(True,),
        kwargs={"agent_playing": False},
    )

    try:
        submitter.start()
        submitter.join(timeout=0.05)
        assert not submitter.is_alive()
    finally:
        contended_lock.release()
        submitter.join(timeout=1.0)
        runtime.close()


def test_full_queue_drops_event_without_raising(tmp_path) -> None:
    session_log = SessionLog(session_id="session-001", session_dir=tmp_path)
    runtime = TurnShadowRuntime(
        session_log=session_log,
        enabled=False,
        queue_size=1,
    )
    runtime._enabled = True

    runtime.submit_wake("hello")
    runtime.submit_vad(True, agent_playing=False)
    runtime.close()

    assert runtime.dropped_count == 1


def test_final_asr_is_first_dynamic_end_of_turn_and_records_latency(
    monkeypatch, tmp_path
) -> None:
    runtime_module = importlib.import_module("turn_detection.runtime_shadow")
    timestamps = iter((1000.0, 1000.1, 1000.2, 1000.9))
    monkeypatch.setattr(runtime_module.time, "time", lambda: next(timestamps))
    session_log = SessionLog(session_id="session-001", session_dir=tmp_path)
    runtime = TurnShadowRuntime(session_log=session_log, enabled=True)

    runtime.submit_wake("hello")
    runtime.submit_vad(True, agent_playing=False)
    runtime.submit_vad(False, agent_playing=False)
    runtime.submit_asr_final("hello there", agent_playing=False)
    runtime.close()

    decisions = [
        json.loads(line)
        for line in (tmp_path / "turn_shadow.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    dynamic = [
        decision for decision in decisions if decision["detector_name"] == "dynamic_v1"
    ]
    assert [decision["decision"] for decision in dynamic] == [
        "UNCERTAIN",
        "CONTINUE_SPEAKING",
        "UNCERTAIN",
        "END_OF_TURN",
    ]
    assert dynamic[-1]["final_text"] == "hello there"
    assert dynamic[-1]["detector_latency_ms"] >= 0.0


def test_agent_playing_provider_runs_on_worker_not_submission_thread(tmp_path) -> None:
    session_log = SessionLog(session_id="session-001", session_dir=tmp_path)
    runtime = TurnShadowRuntime(session_log=session_log, enabled=True)
    submitting_thread = threading.get_ident()
    provider_threads = []

    def agent_playing() -> bool:
        provider_threads.append(threading.get_ident())
        return True

    runtime.submit_vad(True, agent_playing=agent_playing)
    runtime.close()

    decisions = [
        json.loads(line)
        for line in (tmp_path / "turn_shadow.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert provider_threads
    assert all(thread_id != submitting_thread for thread_id in provider_threads)
    assert all(decision["agent_playing"] is True for decision in decisions)
