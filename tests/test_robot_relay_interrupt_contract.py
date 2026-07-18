from pathlib import Path


RELAY_SOURCE = (
    Path(__file__).resolve().parents[1] / "robot_relay" / "jetson_robot_relay.py"
).read_text(encoding="utf-8")


def test_relay_stop_audio_calls_unitree_play_stop():
    assert 'if command == "stop_audio"' in RELAY_SOURCE
    assert "self.audio.PlayStop(app_name)" in RELAY_SOURCE
    assert "_minimum_play_generation" in RELAY_SOURCE
    assert "_stream_is_current" in RELAY_SOURCE
    stop_block = RELAY_SOURCE.split('if command == "stop_audio":', 1)[1].split(
        'if command == "release_arm":', 1
    )[0]
    assert "stale stop audio generation" in stop_block
    assert stop_block.index("stale stop audio generation") < stop_block.index("PlayStop")


def test_relay_release_arm_calls_release_action():
    assert 'if command == "release_arm"' in RELAY_SOURCE
    assert 'self.arm_action.ExecuteAction(action_map["release arm"])' in RELAY_SOURCE
    assert "_minimum_action_generation" in RELAY_SOURCE
    assert "stale action generation" in RELAY_SOURCE
    release_block = RELAY_SOURCE.split('if command == "release_arm":', 1)[1].split(
        'if command == "arm_action":', 1
    )[0]
    assert "stale release arm generation" in release_block
    assert release_block.index("stale release arm generation") < release_block.index("ExecuteAction")
