from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE_SOURCE = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")
PLAYER_SOURCE = (ROOT / "unitree_audio_player.py").read_text(encoding="utf-8")
PLAYER_SOURCE_COMPACT = "".join(PLAYER_SOURCE.split())


def test_llm_turn_discards_results_from_an_older_interrupt_generation():
    assert "turn_generation = self._interrupt_control.current_generation()" in NODE_SOURCE
    assert "generation_changed(turn_generation)" in NODE_SOURCE
    assert '"stale_turn_discarded"' in NODE_SOURCE
    request_section = NODE_SOURCE.split("llm_started_at = time.time()", 1)[1].split(
        'reply = str(llm_response.get("reply", "")).strip()', 1
    )[0]
    assert request_section.index("threading.Thread(target=request_llm, daemon=True).start()") < request_section.index(
        "generation_changed(turn_generation)"
    )
    assert request_section.count("generation_changed(turn_generation)") >= 1


def test_tts_context_carries_interrupt_generation():
    assert '"generation": generation' in NODE_SOURCE
    assert "generation=turn_generation" in NODE_SOURCE


def test_audio_player_aborts_stale_playback_completion_work():
    assert "play_generation" in PLAYER_SOURCE
    assert "_interrupt_control.wait_until" in PLAYER_SOURCE
    assert '"tts_play_interrupted"' in PLAYER_SOURCE
    assert "generation=play_generation" in PLAYER_SOURCE
    assert "relay playback rejected or failed" in PLAYER_SOURCE
    assert "exceptExceptionasexc:" in PLAYER_SOURCE_COMPACT.split(
        "_write_tts_guard(True", 1
    )[1]


def test_active_tts_guard_includes_the_expected_playback_deadline():
    active_guard_call = PLAYER_SOURCE_COMPACT.split("_write_tts_guard(True", 1)[1].split(")", 1)[0]
    assert '"guard_until":safe_audio_end_at' in active_guard_call


def test_relay_backend_does_not_report_cancelled_or_failed_wav_as_success():
    relay_block = PLAYER_SOURCE.split("class RelayUnitreeBackend:", 1)[1].split("def _create_backend", 1)[0]
    assert 'response.get("ret", -1)' in relay_block
    assert 'response.get("cancelled", False)' in relay_block


def test_reply_action_checks_interrupt_generation_before_execution():
    assert "action_generation" in NODE_SOURCE
    assert '"before_action_execute"' in NODE_SOURCE
    assert '"--generation"' in NODE_SOURCE


def test_action_retry_and_delayed_release_keep_interrupt_generation():
    assert "action_generation: int | None = None" in NODE_SOURCE
    assert "self.release_arm(action_generation)" in NODE_SOURCE
    assert "self._execute_classified_action(classification, action_generation)" in NODE_SOURCE
    assert '"stale_before_action_release"' in NODE_SOURCE
