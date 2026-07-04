from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_WAKE_LABEL = "你好小浦"


@dataclass(frozen=True)
class KeywordLine:
    tokens: tuple[str, ...]
    label: str
    raw: str


def load_token_set(tokens_path: Path) -> set[str]:
    tokens: set[str] = set()
    for raw_line in tokens_path.read_text(encoding="utf-8").splitlines():
        parts = raw_line.strip().split()
        if parts:
            tokens.add(parts[0])
    return tokens


def parse_keyword_line(line: str) -> KeywordLine:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return KeywordLine(tokens=(), label="", raw=line)
    if "@" not in raw:
        raise ValueError(f"missing @ label: {line!r}")
    token_part, label = raw.rsplit("@", 1)
    tokens = tuple(part for part in token_part.strip().split() if part)
    label = label.strip()
    if not tokens:
        raise ValueError(f"missing keyword tokens: {line!r}")
    if not label:
        raise ValueError(f"missing keyword label: {line!r}")
    return KeywordLine(tokens=tokens, label=label, raw=line)


def validate_keyword_lines(lines: Iterable[str], token_set: set[str]) -> list[str]:
    errors: list[str] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            parsed = parse_keyword_line(line)
        except ValueError as exc:
            errors.append(f"line {index}: {exc}")
            continue
        missing = [token for token in parsed.tokens if token not in token_set]
        if missing:
            errors.append(
                f"line {index}: unknown token(s): {', '.join(missing)} :: {stripped}"
            )
    return errors


def candidate_xiaopu_keywords(label: str = DEFAULT_WAKE_LABEL) -> list[str]:
    # All variants intentionally emit the same label so downstream wake/session logic
    # sees one canonical wake word no matter how the user says it.
    variants = [
        ("n ǐ h ǎo x iǎo p ǔ", "标准：你好小浦"),
        ("n ǐ h ǎo x iáo p ǔ", "连读/变调：你好小浦"),
        ("n ǐ h ǎo x iǎo p u", "轻声/弱读：你好小浦"),
        ("h ǎi x iǎo p ǔ", "中文口语：嗨小浦"),
        ("h i x iǎo p ǔ", "英文：hi 小浦"),
        ("h ei x iǎo p ǔ", "英文：hey 小浦"),
    ]
    seen: set[str] = set()
    lines: list[str] = []
    for phones, _description in variants:
        line = f"{phones} @{label}"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return lines

