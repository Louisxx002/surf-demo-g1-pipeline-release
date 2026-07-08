from __future__ import annotations

import re
from collections.abc import Iterable


_PUNCTUATION_RE = re.compile(r"[\s，。！？、,.!?;:：；'\"“”‘’\-()（）\[\]{}]+")


def normalize_command_text(text: str) -> str:
    return _PUNCTUATION_RE.sub("", text or "").lower()


def matches_command(text: str, commands: Iterable[str]) -> bool:
    normalized = normalize_command_text(text)
    if not normalized:
        return False

    for command in commands:
        normalized_command = normalize_command_text(command)
        if not normalized_command:
            continue
        if normalized == normalized_command:
            return True
        if _can_match_inside_text(normalized_command) and normalized_command in normalized:
            return True
    return False


def _can_match_inside_text(normalized_command: str) -> bool:
    if not normalized_command:
        return False
    if _contains_cjk(normalized_command):
        return len(normalized_command) >= 2
    return len(normalized_command) >= 3


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)

def looks_like_english_text(text: str) -> bool:
    has_ascii_alpha = bool(re.search(r"[A-Za-z]", text or ""))
    has_cjk = _contains_cjk(text or "")
    return has_ascii_alpha and not has_cjk


def select_terminate_ack_text(text: str, zh_text: str, en_text: str) -> str:
    if looks_like_english_text(text) and en_text.strip():
        return en_text.strip()
    return zh_text.strip()

