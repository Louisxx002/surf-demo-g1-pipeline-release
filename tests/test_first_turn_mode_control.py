from pathlib import Path

import pytest

from first_turn.mode_control import (
    COMPATIBLE_MODE,
    STANDARD_MODE,
    FirstTurnModeStore,
    normalize_first_turn_mode,
)


def test_first_turn_mode_store_defaults_to_standard(tmp_path: Path) -> None:
    store = FirstTurnModeStore(tmp_path / "first_turn_mode.json")

    assert store.read() == STANDARD_MODE


def test_first_turn_mode_store_persists_compatible_mode(tmp_path: Path) -> None:
    store = FirstTurnModeStore(tmp_path / "first_turn_mode.json")

    assert store.write(COMPATIBLE_MODE) == COMPATIBLE_MODE
    assert store.read() == COMPATIBLE_MODE


def test_first_turn_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        normalize_first_turn_mode("unknown")
