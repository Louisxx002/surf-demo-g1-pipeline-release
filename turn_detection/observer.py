from __future__ import annotations

from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import threading
from typing import Iterable

from turn_detection.models import TurnDecision


_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.Lock] = {}


def _path_lock(path: Path) -> threading.Lock:
    key = path.resolve()
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.Lock())


def _event_ids(lines: Iterable[str]) -> set[str]:
    event_ids: set[str] = set()
    for line in lines:
        try:
            payload = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        event_id = payload.get("event_id") if isinstance(payload, dict) else None
        if type(event_id) is str and event_id:
            event_ids.add(event_id)
    return event_ids


def _event_ids_from_fd(fd: int) -> set[str]:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(fd, 64 * 1024):
        chunks.append(chunk)
    text = b"".join(chunks).decode("utf-8", errors="replace")
    return _event_ids(text.splitlines())


def _repair_jsonl_tail(fd: int) -> int:
    size = os.fstat(fd).st_size
    if size == 0:
        return 0
    os.lseek(fd, size - 1, os.SEEK_SET)
    if os.read(fd, 1) == b"\n":
        return size

    cursor = size
    suffix: list[bytes] = []
    tail_start = 0
    tail = b""
    while cursor > 0:
        read_start = max(0, cursor - 64 * 1024)
        os.lseek(fd, read_start, os.SEEK_SET)
        chunk = os.read(fd, cursor - read_start)
        newline_index = chunk.rfind(b"\n")
        if newline_index >= 0:
            tail_start = read_start + newline_index + 1
            tail = chunk[newline_index + 1 :] + b"".join(suffix)
            break
        suffix.insert(0, chunk)
        cursor = read_start
    else:
        tail = b"".join(suffix)

    try:
        payload = json.loads(tail.decode("utf-8"))
        valid_tail = isinstance(payload, dict)
    except (UnicodeError, json.JSONDecodeError):
        valid_tail = False
    if valid_tail:
        os.lseek(fd, 0, os.SEEK_END)
        os.write(fd, b"\n")
        return size + 1

    os.ftruncate(fd, tail_start)
    return tail_start


class TurnDecisionObserver:
    def __init__(self, output_path: Path) -> None:
        self.output_path = Path(output_path)
        self._seen_event_ids = self._load_event_ids()
        try:
            self._known_size = self.output_path.stat().st_size
        except OSError:
            self._known_size = 0

    def _load_event_ids(self) -> set[str]:
        try:
            with self.output_path.open("r", encoding="utf-8") as stream:
                return _event_ids(stream)
        except (OSError, UnicodeError):
            return set()

    def _append(self, event_id: str, line: str) -> bool:
        data = line.encode("utf-8")
        with _path_lock(self.output_path):
            fd = os.open(self.output_path, os.O_APPEND | os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    repaired_size = _repair_jsonl_tail(fd)
                    if repaired_size != self._known_size:
                        self._seen_event_ids.update(_event_ids_from_fd(fd))
                        self._known_size = repaired_size
                    if event_id in self._seen_event_ids:
                        return False
                    original_size = os.fstat(fd).st_size
                    try:
                        written = os.write(fd, data)
                        if written != len(data):
                            os.ftruncate(fd, original_size)
                            return False
                    except Exception:
                        os.ftruncate(fd, original_size)
                        raise
                    self._seen_event_ids.add(event_id)
                    self._known_size = original_size + len(data)
                    return True
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def observe(self, event: object) -> bool:
        try:
            if not isinstance(event, TurnDecision):
                return False
            if type(event.event_id) is not str or not event.event_id.strip():
                return False
            if event.event_id in self._seen_event_ids:
                return False
            line = json.dumps(asdict(event), ensure_ascii=False) + "\n"
            return self._append(event.event_id, line)
        except Exception:
            return False
