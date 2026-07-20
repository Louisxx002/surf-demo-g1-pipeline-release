import json
import threading
import time

import pytest

from pipeline_control.interrupt import InterruptControl


def test_issue_interrupt_increments_generation_and_opens_listening(tmp_path):
    control = InterruptControl(tmp_path)

    first = control.issue(session_id="session-1", followup_timeout_sec=15)
    second = control.issue(session_id="session-1", followup_timeout_sec=15)

    assert first["generation"] == 1
    assert second["generation"] == 2
    assert control.current_generation() == 2

    followup = json.loads((tmp_path / "followup_control.json").read_text(encoding="utf-8"))
    assert followup["command"] == "open"
    assert followup["session_id"] == "session-1"
    assert followup["reason"] == "manual_interrupt"
    assert followup["timeout_sec"] == 15

    guard = json.loads((tmp_path / "tts_guard.json").read_text(encoding="utf-8"))
    assert guard["active"] is False
    assert guard["guard_until"] <= guard["updated_at"]


def test_begin_interrupt_does_not_open_listening_until_explicitly_requested(tmp_path):
    control = InterruptControl(tmp_path)

    command = control.begin(session_id="session-1")

    assert command["generation"] == 1
    assert not (tmp_path / "followup_control.json").exists()
    assert not (tmp_path / "tts_guard.json").exists()

    control.open_listening(command, followup_timeout_sec=15)

    followup = json.loads((tmp_path / "followup_control.json").read_text(encoding="utf-8"))
    assert followup["command"] == "open"
    assert followup["session_id"] == "session-1"


def test_stale_interrupt_cannot_reopen_listening(tmp_path):
    control = InterruptControl(tmp_path)
    stale = control.begin(session_id="session-old")
    current = control.begin(session_id="session-new")

    with pytest.raises(RuntimeError, match="stale interrupt generation"):
        control.open_listening(stale, followup_timeout_sec=15)

    assert not (tmp_path / "followup_control.json").exists()
    control.open_listening(current, followup_timeout_sec=15)
    followup = json.loads((tmp_path / "followup_control.json").read_text(encoding="utf-8"))
    assert followup["session_id"] == "session-new"


def test_concurrent_interrupts_allocate_distinct_generations(tmp_path):
    control = InterruptControl(tmp_path)
    barrier = threading.Barrier(3)
    generations = []

    def issue_one():
        barrier.wait()
        generations.append(control.begin(session_id="session-1")["generation"])

    threads = [threading.Thread(target=issue_one) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert sorted(generations) == [1, 2]
    assert control.current_generation() == 2


def test_generation_changed_detects_stale_work(tmp_path):
    control = InterruptControl(tmp_path)
    original = control.current_generation()

    assert not control.generation_changed(original)
    control.issue(session_id="session-1")
    assert control.generation_changed(original)


def test_corrupt_command_file_recovers_from_zero(tmp_path):
    (tmp_path / "interrupt_command.json").write_text("not-json", encoding="utf-8")
    control = InterruptControl(tmp_path)

    payload = control.issue(session_id="session-2")

    assert payload["generation"] == 1
    assert control.current_generation() == 1


def test_wait_until_returns_false_when_generation_is_stale(tmp_path):
    control = InterruptControl(tmp_path)
    generation = control.current_generation()
    control.issue(session_id="session-3")

    assert control.wait_until(time.time() + 1, generation) is False


def test_wait_until_returns_true_when_deadline_is_reached(tmp_path):
    control = InterruptControl(tmp_path)
    generation = control.current_generation()

    assert control.wait_until(time.time() + 0.01, generation, poll_sec=0.002) is True


def test_playback_active_reads_live_tts_guard(tmp_path):
    control = InterruptControl(tmp_path)
    (tmp_path / "tts_guard.json").write_text(
        json.dumps({"active": True, "guard_until": time.time() + 5}),
        encoding="utf-8",
    )

    assert control.playback_active() is True


def test_request_session_end_writes_generation_without_opening_listening(tmp_path):
    control = InterruptControl(tmp_path)

    command = control.request_session_end(session_id="s001", user_text="")

    payload = json.loads((tmp_path / "session_command.json").read_text(encoding="utf-8"))
    assert payload["command"] == "end_session"
    assert payload["session_id"] == "s001"
    assert payload["generation"] == command["generation"]
    assert not (tmp_path / "followup_control.json").exists()
