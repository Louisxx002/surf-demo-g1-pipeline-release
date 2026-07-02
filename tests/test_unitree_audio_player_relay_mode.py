import ast
from pathlib import Path


def test_unitree_sdk_imports_are_not_at_module_top_level():
    source_path = Path(__file__).resolve().parents[1] / "unitree_audio_player.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))

    top_level_imports = []
    for node in module.body:
        if isinstance(node, ast.Import):
            top_level_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.append(node.module)

    assert not any(name.startswith("unitree_sdk2py") for name in top_level_imports)


def test_audio_player_has_relay_backend_without_direct_audio_client():
    source_path = Path(__file__).resolve().parents[1] / "unitree_audio_player.py"
    source = source_path.read_text(encoding="utf-8")

    assert "class RelayUnitreeBackend" in source
    assert "RobotRelayClient" in source
    assert "AudioClient()" in source
    assert source.index("class RelayUnitreeBackend") < source.index("def _create_backend")


def test_relay_backend_uses_wav_playback_not_text_tts():
    source_path = Path(__file__).resolve().parents[1] / "unitree_audio_player.py"
    source = source_path.read_text(encoding="utf-8")
    relay_block = source.split("class RelayUnitreeBackend:", 1)[1].split("def _create_backend", 1)[0]

    assert "self.client.play_wav(" in relay_block
    assert "self.client.say_text(" not in relay_block


def test_audio_player_caps_unreasonable_duration_waits():
    source_path = Path(__file__).resolve().parents[1] / "unitree_audio_player.py"
    source = source_path.read_text(encoding="utf-8")

    assert "MAX_REASONABLE_TTS_DURATION_SEC" in source
    assert "unreasonable wav duration" in source
    assert "return 0.0" in source


def test_audio_player_waits_for_stable_tts_file_before_playback():
    source_path = Path(__file__).resolve().parents[1] / "unitree_audio_player.py"
    source = source_path.read_text(encoding="utf-8")

    assert "def _wait_for_stable_file" in source
    assert "_wait_for_stable_file(CONFIG.tts_wav_path)" in source
