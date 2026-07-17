from __future__ import annotations

import re
from typing import Any


ACTION_IDS = {
    "释放手臂": 99,
    "双手飞吻": 11,
    "右手飞吻": 13,
    "左手飞吻": 12,
    "举双手": 15,
    "鼓掌": 17,
    "击掌": 18,
    "拥抱": 19,
    "比心": 20,
    "右手比心": 21,
    "拒绝摆手": 22,
    "举右手": 23,
    "x-ray": 24,
    "面前挥手": 25,
    "高位挥手": 26,
    "握手": 27,
}

OFFICIAL_NAMES = {
    "无动作": "none",
    "释放手臂": "release arm",
    "双手飞吻": "two-hand kiss",
    "右手飞吻": "right kiss",
    "左手飞吻": "left kiss",
    "举双手": "hands up",
    "鼓掌": "clap",
    "击掌": "high five",
    "拥抱": "hug",
    "比心": "heart",
    "右手比心": "right heart",
    "拒绝摆手": "reject",
    "举右手": "right hand up",
    "x-ray": "x-ray",
    "面前挥手": "face wave",
    "高位挥手": "high wave",
    "握手": "shake hand",
}

NO_ACTION_CONTEXTS = {"wake_ack", "system_ack", "session_end", "error"}
STILL_PHRASES = (
    "不要动",
    "别动",
    "不用动",
    "保持不动",
    "不要做动作",
    "别做动作",
)
SELF_INTRO_PHRASES = (
    "你是谁",
    "你叫什么",
    "介绍一下你自己",
    "自我介绍",
    "我是小浦",
    "我叫小浦",
)
GREETING_PHRASES = ("你好", "您好")
WELCOME_PHRASES = ("欢迎",)
ENGLISH_SOCIAL_PATTERN = re.compile(r"\b(?:hi|hello|hey|welcome)\b", re.IGNORECASE)
EXPLICIT_ACTION_PHRASES = (
    "挥个手",
    "请挥手",
    "帮我挥手",
    "打个招呼",
    "握个手",
    "和我握手",
    "请鼓掌",
    "鼓个掌",
    "和我击掌",
    "比个心",
    "抱一下",
    "拥抱我",
    "给我一个拥抱",
    "来个飞吻",
    "举个手",
    "请抬手",
    "帮我抬手",
    "摆个手",
    "做个动作",
    "做一个动作",
    "来个动作",
    "表演一下",
    "欢迎一下",
    "示意一下",
    "执行xray",
    "执行x-ray",
    "做一个x光动作",
)
DIRECT_ACTION_COMMANDS = {
    "挥手",
    "握手",
    "鼓掌",
    "击掌",
    "比心",
    "拥抱",
    "飞吻",
    "举手",
    "抬手",
    "摆手",
    "跳舞",
    "释放手臂",
    "放下手",
    "拒绝摆手",
    "动作",
    "xray",
    "x-ray",
    "x光",
}


def _classification(
    label: str,
    backend: str,
    reason: str,
    *,
    score: float = 1.0,
    text: str = "",
) -> dict[str, Any]:
    action_id = ACTION_IDS.get(label, -1)
    return {
        "text": text,
        "label": label,
        "official_name": OFFICIAL_NAMES.get(label, "none"),
        "action_id": action_id,
        "score": score,
        "backend": backend,
        "should_execute": action_id >= 0,
        "reason": reason,
    }


def _no_action(text: str, backend: str, reason: str) -> dict[str, Any]:
    return _classification("无动作", backend, reason, score=0.0, text=text)


def _normalized_text(value: str) -> str:
    return "".join(str(value or "").lower().split())


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    compact = _normalized_text(text)
    return any(_normalized_text(phrase) in compact for phrase in phrases)


def _is_social_greeting(reply: str, user_text: str) -> bool:
    combined = f"{user_text}\n{reply}"
    return (
        _contains_any(combined, SELF_INTRO_PHRASES)
        or _contains_any(combined, GREETING_PHRASES)
        or _contains_any(combined, WELCOME_PHRASES)
        or ENGLISH_SOCIAL_PATTERN.search(combined) is not None
    )


def is_explicit_action_request(user_text: str) -> bool:
    """Return true only for direct requests to move, not reply semantics."""

    compact = _normalized_text(user_text)
    return compact in DIRECT_ACTION_COMMANDS or _contains_any(
        user_text, EXPLICIT_ACTION_PHRASES
    )


def _valid_candidate(
    candidate: dict[str, Any] | None,
    threshold: float,
) -> dict[str, Any] | None:
    if not candidate:
        return None
    label = str(candidate.get("label", "")).strip()
    expected_id = ACTION_IDS.get(label)
    if expected_id is None:
        return None
    try:
        action_id = int(candidate.get("action_id", -1))
        score = float(candidate.get("score", 0.0))
    except (TypeError, ValueError):
        return None
    if action_id != expected_id or score < threshold:
        return None
    result = dict(candidate)
    result["should_execute"] = True
    return result


def resolve_reply_action(
    *,
    reply: str,
    user_text: str = "",
    deepseek_action: dict[str, Any] | None = None,
    explicit_action: dict[str, Any] | None = None,
    semantic_action: dict[str, Any] | None = None,
    threshold: float = 0.8,
    frequent_reply_enabled: bool = True,
    context_kind: str = "reply",
) -> dict[str, Any]:
    """Choose one semantic reply action without executing it."""

    if context_kind in NO_ACTION_CONTEXTS:
        return _no_action(reply, "system_no_action", context_kind)

    if _contains_any(user_text, STILL_PHRASES):
        return _no_action(reply, "explicit_no_action", "user_requested_stillness")

    explicit = _valid_candidate(explicit_action, threshold)
    if explicit is not None:
        return explicit

    if frequent_reply_enabled and _is_social_greeting(reply, user_text):
        return _classification(
            "高位挥手",
            "reply_self_intro",
            "self introduction, greeting, or welcome",
            score=0.98,
            text=reply,
        )

    deepseek = _valid_candidate(deepseek_action, threshold)
    if deepseek is not None:
        return deepseek

    semantic = _valid_candidate(semantic_action, threshold)
    if semantic is not None:
        return semantic

    if frequent_reply_enabled and str(reply or "").strip():
        return _classification(
            "举右手",
            "reply_info_fallback",
            "safe informational reply fallback",
            score=0.9,
            text=reply,
        )

    if deepseek_action:
        result = dict(deepseek_action)
        result["should_execute"] = False
        return result

    return _no_action(reply, "no_action", "no valid action candidate")
