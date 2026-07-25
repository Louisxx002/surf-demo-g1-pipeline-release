from __future__ import annotations

import json
import os
from pathlib import Path


STANDARD_MODE = "standard"
COMPATIBLE_MODE = "compatible"
VALID_MODES = frozenset({STANDARD_MODE, COMPATIBLE_MODE})


def normalize_first_turn_mode(mode: str) -> str:
    value = str(mode).strip().lower()
    if value not in VALID_MODES:
        raise ValueError(f"unsupported first-turn mode: {mode}")
    return value


class FirstTurnModeStore:
    """Durable first-turn mode shared by the monitor and pipeline launcher."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def read(self) -> str:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return normalize_first_turn_mode(payload.get("mode", STANDARD_MODE))
        except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError, TypeError):
            return STANDARD_MODE

    def write(self, mode: str) -> str:
        value = normalize_first_turn_mode(mode)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps({"mode": value}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return value
