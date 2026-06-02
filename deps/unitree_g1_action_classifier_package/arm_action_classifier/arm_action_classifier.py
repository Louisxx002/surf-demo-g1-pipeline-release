#!/usr/bin/env python3
"""Classify text to Unitree G1 preset arm actions and optionally execute them."""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
DEFAULT_QWEN_MODEL = "qwen-plus"
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass(frozen=True)
class ArmAction:
    label: str
    official_name: str
    action_id: int
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class ReplyIntent:
    label: str
    action_label: str


@dataclass(frozen=True)
class ClassificationResult:
    text: str
    label: str
    official_name: str
    action_id: int
    score: float
    backend: str
    should_execute: bool
    reason: str = ""


NO_ACTION = ArmAction("无动作", "none", -1, ("不用动", "不要动", "别动", "保持不动", "无需动作", "什么都不做", "不需要动作"))

ACTIONS: tuple[ArmAction, ...] = (
    NO_ACTION,
    ArmAction("释放手臂", "release arm", 99, ("释放", "复位", "放松", "收回", "release")),
    ArmAction("双手飞吻", "two-hand kiss", 11, ("双手飞吻", "两手飞吻", "双手飞吻一下", "両手キス", "両手でキス", "two hand kiss")),
    ArmAction(
        "右手飞吻",
        "right kiss",
        13,
        (
            "单手飞吻",
            "右手飞吻",
            "右边飞吻",
            "右侧飞吻",
            "飞吻",
            "亲吻",
            "亲亲",
            "亲一下",
            "亲一个",
            "么么",
            "么么哒",
            "mua",
            "kiss",
            "キス",
            "キッス",
            "ちゅー",
            "ちゅっ",
            "チュー",
            "single hand kiss",
            "right kiss",
            "right hand kiss",
        ),
    ),
    ArmAction(
        "左手飞吻",
        "left kiss",
        12,
        (
            "左手飞吻",
            "左边飞吻",
            "左侧飞吻",
            "left kiss",
            "left hand kiss",
        ),
    ),
    ArmAction("举双手", "hands up", 15, ("举双手", "双手举起", "投降", "hands up", "万歳", "ばんざい", "両手を上げる")),
    ArmAction("鼓掌", "clap", 17, ("鼓掌", "鼓个掌", "拍手", "拍个手", "掌声", "太棒了", "真棒", "做得好", "恭喜", "祝贺", "clap", "拍手喝采", "すごい", "おめでとう", "やった")),
    ArmAction("击掌", "high five", 18, ("击掌", "击个掌", "high five", "合作愉快", "我们成功了", "ハイタッチ", "ハイファイブ")),
    ArmAction("拥抱", "hug", 19, ("拥抱", "抱一下", "抱抱", "安慰你", "别难过", "hug", "ハグ", "ぎゅっ", "ぎゅー", "抱きしめる")),
    ArmAction("比心", "heart", 20, ("比心", "比个心", "爱心", "谢谢", "感谢", "喜欢你", "爱你", "heart", "ハート", "大好き", "ありがとう", "好き", "愛してる")),
    ArmAction("右手比心", "right heart", 21, ("右手比心", "右边比心", "右手ハート")),
    ArmAction("拒绝摆手", "reject", 22, ("拒绝", "不要", "不行", "不可以", "不能", "抱歉不行", "摆手拒绝", "reject", "だめ", "無理", "できない", "ごめん", "ごめんなさい")),
    ArmAction("举右手", "right hand up", 23, ("举右手", "右手举起", "抬右手", "右手を上げる")),
    ArmAction("x-ray", "x-ray", 24, ("xray", "x-ray", "x光", "エックス線", "X線")),
    ArmAction("面前挥手", "face wave", 25, ("面前挥手", "脸前挥手", "近处挥手", "目の前で手を振る")),
    ArmAction("高位挥手", "high wave", 26, ("挥手", "挥挥手", "招手", "高位挥手", "打招呼", "你好", "您好", "大家好", "hello", "hi", "哈喽", "再见", "拜拜", "wave", "こんにちは", "こんばんは", "おはよう", "さようなら", "はじめまして", "やあ", "ハロー", "またね", "バイバイ")),
    ArmAction("握手", "shake hand", 27, ("握手", "握个手", "认识你很高兴", "很高兴认识你", "shake hand", "handshake", "よろしく", "よろしくお願いします", "はじめまして")),
)

REPLY_INTENTS: tuple[ReplyIntent, ...] = (
    ReplyIntent("没有合适的手臂动作", "无动作"),
    ReplyIntent("问候、欢迎、告别、社交打招呼", "高位挥手"),
    ReplyIntent("感谢、喜欢、表达友好和爱意", "比心"),
    ReplyIntent("赞美、认可、庆祝、觉得很棒", "鼓掌"),
    ReplyIntent("成功合作、达成一致、互动庆祝", "击掌"),
    ReplyIntent("安慰、鼓励、亲近和陪伴", "拥抱"),
    ReplyIntent("拒绝、道歉、不能做、不允许", "拒绝摆手"),
    ReplyIntent("初次见面、正式认识、建立连接", "握手"),
)


def normalize(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?]", "", text.lower())


def classify_keyword(text: str, threshold: float) -> ClassificationResult:
    normalized = normalize(text)
    reply_rule_result = classify_reply_rules(text, threshold)
    if reply_rule_result.action_id != -999:
        return reply_rule_result

    best_action: ArmAction | None = None
    best_score = 0.0

    for action in ACTIONS:
        for alias in action.aliases:
            alias_norm = normalize(alias)
            if normalized == alias_norm:
                best_action = action
                best_score = 0.98
            elif alias_norm and alias_norm in normalized and best_score < 0.9:
                best_action = action
                best_score = 0.9

    if best_action is None:
        return unknown_result(text, "keyword")

    return to_result(text, best_action, best_score, "keyword", threshold)


def classify_reply_rules(text: str, threshold: float) -> ClassificationResult:
    normalized = normalize(text)
    rules: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("reply_no_action", "无动作", ("不用动", "不要动", "别动", "保持不动", "无需动作", "什么都不做", "不需要动作")),
        ("reply_aggressive_xray", "x-ray", ("攻击", "打人", "打你", "揍", "伤害", "消灭", "干掉", "毁灭", "威胁", "挑衅", "目标锁定", "开火")),
        ("reply_greeting", "高位挥手", ("你好", "您好", "大家好", "哈喽", "hello", "hi", "再见", "拜拜", "欢迎", "こんにちは", "こんばんは", "おはよう", "さようなら", "はじめまして", "やあ", "ハロー", "またね")),
        ("reply_two_hand_kiss", "双手飞吻", ("双手飞吻", "两手飞吻", "双手飞吻一下", "両手キス", "両手でキス")),
        ("reply_right_kiss", "右手飞吻", ("右手飞吻", "右边飞吻", "右侧飞吻", "right kiss", "right hand kiss")),
        ("reply_left_kiss", "左手飞吻", ("左手飞吻", "左边飞吻", "左侧飞吻", "left kiss", "left hand kiss")),
        (
            "reply_kiss",
            "右手飞吻",
            ("飞吻", "么么", "么么哒", "亲一个", "亲亲", "亲你", "亲一下", "kiss", "kiss一下", "mua", "キス", "キッス", "ちゅー", "ちゅっ", "チュー"),
        ),
        ("reply_gratitude_affection", "比心", ("谢谢", "感谢", "喜欢", "爱你", "爱意", "暖心", "贴心", "ありがとう", "大好き", "好き")),
        ("reply_praise_celebration", "鼓掌", ("棒", "优秀", "厉害", "出色", "精彩", "不错", "赞", "成功", "恭喜", "祝贺", "了不起", "すごい", "おめでとう", "やった")),
        ("reply_high_five", "击掌", ("合作愉快", "达成一致", "我们成功了", "干得漂亮", "ハイタッチ", "ハイファイブ")),
        ("reply_comfort", "拥抱", ("别难过", "安慰", "陪着你", "抱抱", "没关系", "不要伤心", "ハグ", "ぎゅっ", "ぎゅー")),
        ("reply_reject", "拒绝摆手", ("不能", "不可以", "不行", "抱歉", "对不起", "拒绝", "无法", "だめ", "無理", "できない", "ごめん", "ごめんなさい")),
        ("reply_handshake", "握手", ("认识你很高兴", "很高兴认识你", "初次见面", "幸会", "よろしく", "よろしくお願いします", "はじめまして")),
    )

    for backend, action_label, patterns in rules:
        if any(pattern in normalized for pattern in patterns):
            action = find_by_label(action_label)
            return to_result(text, action, 0.92, backend, threshold)

    return ClassificationResult(
        text=text,
        label="__no_reply_rule__",
        official_name="__no_reply_rule__",
        action_id=-999,
        score=0.0,
        backend="reply_rules",
        should_execute=False,
    )


def classify_hf(text: str, model: str, threshold: float) -> ClassificationResult:
    keyword_result = classify_keyword(text, threshold)
    if (
        keyword_result.action_id == -1
        and keyword_result.label == NO_ACTION.label
        and keyword_result.score > 0.0
    ):
        return ClassificationResult(
            text=text,
            label=NO_ACTION.label,
            official_name=NO_ACTION.official_name,
            action_id=NO_ACTION.action_id,
            score=keyword_result.score,
            backend="explicit_no_action",
            should_execute=False,
        )

    if keyword_result.action_id >= 0 and keyword_result.score >= 0.98:
        return ClassificationResult(
            text=text,
            label=keyword_result.label,
            official_name=keyword_result.official_name,
            action_id=keyword_result.action_id,
            score=keyword_result.score,
            backend="hf+keyword",
            should_execute=True,
        )

    try:
        from transformers import pipeline
    except ImportError as exc:
        raise SystemExit(
            "缺少 Hugging Face 依赖。请先执行：python3 -m pip install transformers torch"
        ) from exc

    classifier = pipeline("zero-shot-classification", model=model)
    labels = [intent.label for intent in REPLY_INTENTS]
    output: dict[str, Any] = classifier(
        text,
        candidate_labels=labels,
        hypothesis_template="这句机器人回复表达的是{}。",
        multi_label=False,
    )

    intent_label = output["labels"][0]
    score = float(output["scores"][0])
    intent = find_intent_by_label(intent_label)
    action = find_by_label(intent.action_label)
    hf_result = to_result(text, action, score, "hf", threshold)
    if action.action_id == -1:
        return ClassificationResult(
            text=text,
            label=NO_ACTION.label,
            official_name=NO_ACTION.official_name,
            action_id=NO_ACTION.action_id,
            score=score,
            backend="hf_intent_no_action",
            should_execute=False,
        )

    if hf_result.action_id == 99 and keyword_result.action_id != 99:
        return ClassificationResult(
            text=text,
            label=hf_result.label,
            official_name=hf_result.official_name,
            action_id=hf_result.action_id,
            score=hf_result.score,
            backend="hf_intent_requires_explicit_release_arm",
            should_execute=False,
        )
    if hf_result.should_execute:
        return hf_result

    if keyword_result.action_id < 0:
        return ClassificationResult(
            text=text,
            label=NO_ACTION.label,
            official_name=NO_ACTION.official_name,
            action_id=NO_ACTION.action_id,
            score=hf_result.score,
            backend="low_confidence_no_action",
            should_execute=False,
        )

    return ClassificationResult(
        text=text,
        label=keyword_result.label,
        official_name=keyword_result.official_name,
        action_id=keyword_result.action_id,
        score=keyword_result.score,
        backend="keyword_after_low_confidence_hf",
        should_execute=keyword_result.should_execute,
        reason="Hugging Face 置信度不足，使用本地 reply 意图规则兜底。",
    )


def classify_qwen(
    text: str,
    model: str,
    base_url: str,
    threshold: float,
    keyword_first: bool = True,
) -> ClassificationResult:
    if keyword_first:
        keyword_result = classify_keyword(text, threshold)
        if keyword_result.action_id >= 0 and keyword_result.score >= threshold:
            return ClassificationResult(
                text=text,
                label=keyword_result.label,
                official_name=keyword_result.official_name,
                action_id=keyword_result.action_id,
                score=keyword_result.score,
                backend="qwen+keyword_first",
                should_execute=True,
                reason="明确关键词或本地 reply 规则命中，跳过 DashScope 分类。",
            )
        if (
            keyword_result.action_id == -1
            and keyword_result.label == NO_ACTION.label
            and keyword_result.score >= threshold
        ):
            return ClassificationResult(
                text=text,
                label=NO_ACTION.label,
                official_name=NO_ACTION.official_name,
                action_id=NO_ACTION.action_id,
                score=keyword_result.score,
                backend="qwen+explicit_no_action",
                should_execute=False,
                reason="明确无动作规则命中，跳过 DashScope 分类。",
            )

    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise SystemExit(
            "缺少 DASHSCOPE_API_KEY。请先执行：export DASHSCOPE_API_KEY='你的百炼APIKey'"
        )
    if any(ord(char) > 127 for char in api_key):
        raise SystemExit(
            "DASHSCOPE_API_KEY 包含非 ASCII 字符。请把占位符替换成真实百炼 API Key，例如：export DASHSCOPE_API_KEY='sk-...'"
        )

    labels = [action.label for action in ACTIONS]
    action_table = [
        {"label": action.label, "official_name": action.official_name, "action_id": action.action_id}
        for action in ACTIONS
    ]
    system_prompt = (
        "你是机器人手臂动作分类器。输入是一句机器人将要回复给用户的话，"
        "不是用户命令。请判断这句回复最适合搭配哪个手臂动作。"
        "输入可能是中文、英文或日文。"
        "只能从给定动作标签中选择一个。"
        "如果回复只是信息说明、查询结果、普通陈述、无法用动作表达、或不适合动，选择“无动作”。"
        "如果回复包含攻击、威胁、伤害、挑衅、打人、消灭、攻击目标等具有攻击性的舞台化表达，选择“x-ray”。"
        "这里的“x-ray”只是非接触的表演动作，不代表真实攻击。"
        "输出必须是严格 JSON，不要 Markdown，不要额外文字。"
    )
    user_prompt = {
        "reply_text": text,
        "available_actions": action_table,
        "output_schema": {
            "label": "必须是 available_actions 中的 label",
            "confidence": "0到1之间的数字",
            "reason": "一句简短中文理由",
        },
        "examples": [
            {"reply_text": "你好，很高兴见到你", "label": "高位挥手"},
            {"reply_text": "西交利物浦大学非常棒", "label": "鼓掌"},
            {"reply_text": "ありがとうございます、大好きです", "label": "比心"},
            {"reply_text": "こんにちは、はじめまして", "label": "高位挥手"},
            {"reply_text": "すごいですね、おめでとう", "label": "鼓掌"},
            {"reply_text": "抱歉，这个我不能做", "label": "拒绝摆手"},
            {"reply_text": "我可以帮你查询天气信息", "label": "无动作"},
            {"reply_text": "我要攻击前方目标", "label": "x-ray"},
            {"reply_text": "ハイタッチしよう", "label": "击掌"},
        ],
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    response_data = post_chat_completion(base_url, api_key, payload)
    content = response_data["choices"][0]["message"]["content"]
    parsed = parse_json_object(content)

    label = str(parsed.get("label", "无动作"))
    confidence = float(parsed.get("confidence", 0.0))
    reason = str(parsed.get("reason", ""))
    if label not in labels:
        label = "无动作"
        confidence = 0.0
        reason = "模型返回了动作白名单之外的标签。"

    action = find_by_label(label)
    should_execute = action.action_id >= 0 and confidence >= threshold
    return ClassificationResult(
        text=text,
        label=action.label,
        official_name=action.official_name,
        action_id=action.action_id,
        score=confidence,
        backend="qwen",
        should_execute=should_execute,
        reason=reason,
    )


def post_chat_completion(base_url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    context = ssl.create_default_context(cafile=get_certifi_ca_file())
    try:
        with urllib.request.urlopen(request, timeout=60, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except UnicodeEncodeError as exc:
        raise SystemExit(
            "通义千问 API 请求失败：DASHSCOPE_API_KEY 里包含无法放入 HTTP Header 的字符。请确认已设置真实 API Key，而不是中文占位符。"
        ) from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"通义千问 API 请求失败：HTTP {exc.code}\n{detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"通义千问 API 网络请求失败：{exc}") from exc


def get_certifi_ca_file() -> str | None:
    try:
        import certifi
    except ImportError:
        return None
    return certifi.where()


def parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise SystemExit(f"模型没有返回 JSON：{content}")
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise SystemExit(f"模型返回 JSON 不是对象：{content}")
    return parsed


def find_by_label(label: str) -> ArmAction:
    for action in ACTIONS:
        if action.label == label:
            return action
    raise ValueError(f"Unknown label from classifier: {label}")


def find_intent_by_label(label: str) -> ReplyIntent:
    for intent in REPLY_INTENTS:
        if intent.label == label:
            return intent
    raise ValueError(f"Unknown intent from classifier: {label}")


def to_result(
    text: str,
    action: ArmAction,
    score: float,
    backend: str,
    threshold: float,
) -> ClassificationResult:
    return ClassificationResult(
        text=text,
        label=action.label,
        official_name=action.official_name,
        action_id=action.action_id,
        score=score,
        backend=backend,
        should_execute=action.action_id >= 0 and score >= threshold,
    )


def unknown_result(text: str, backend: str) -> ClassificationResult:
    return ClassificationResult(
        text=text,
        label=NO_ACTION.label,
        official_name=NO_ACTION.official_name,
        action_id=-1,
        score=0.0,
        backend=backend,
        should_execute=False,
    )


def execute_action(result: ClassificationResult, network: str, runner: str) -> dict[str, Any]:
    if result.action_id < 0:
        return {"executed": False, "reason": "unknown_action"}
    if not result.should_execute:
        return {"executed": False, "reason": "score_below_threshold"}
    if not network:
        return {"executed": False, "reason": "--network is required"}
    if not os.path.exists(runner):
        return {"executed": False, "reason": f"runner not found: {runner}"}

    command = [runner, "--network", network, "--id", str(result.action_id)]
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        env=build_runner_env(runner),
    )
    output = completed.stdout + completed.stderr
    if "The actions are only supported in fsm id" in output:
        return {
            "executed": False,
            "reason": "invalid_fsm_id",
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    if "The arm is holding" in output:
        return {
            "executed": False,
            "reason": "arm_holding_release_required",
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    if "Execute action failed" in output or "Invalid action id" in output:
        return {
            "executed": False,
            "reason": "runner_reported_failure",
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    return {
        "executed": completed.returncode == 0,
        "reason": "runner_nonzero_returncode" if completed.returncode != 0 else "runner_completed",
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def build_runner_env(runner: str) -> dict[str, str]:
    env = os.environ.copy()
    runner_abs = os.path.abspath(runner)
    sdk_root = os.path.abspath(os.path.join(os.path.dirname(runner_abs), "..", ".."))
    arch = os.uname().machine
    unitree_lib_dir = os.path.join(sdk_root, "thirdparty", "lib", arch)
    if os.path.isdir(unitree_lib_dir):
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = unitree_lib_dir + (f":{existing}" if existing else "")
    return env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify text to Unitree G1 arm actions.")
    parser.add_argument("text", nargs="?", help="LLM or ASR text")
    parser.add_argument("--backend", choices=("qwen", "hf", "keyword"), default="qwen")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face zero-shot model id")
    parser.add_argument("--qwen-model", default=DEFAULT_QWEN_MODEL, help="DashScope Qwen model id")
    parser.add_argument("--qwen-base-url", default=DEFAULT_QWEN_BASE_URL, help="DashScope OpenAI-compatible base URL")
    parser.add_argument("--threshold", type=float, default=0.8, help="Minimum score to execute")
    parser.add_argument("--execute", action="store_true", help="Execute official G1 arm action")
    parser.add_argument("--no-keyword-first", action="store_true", help="Do not use local keyword/reply rules before qwen API")
    parser.add_argument("--network", default="", help="DDS network interface, e.g. eth0")
    parser.add_argument(
        "--runner",
        default="../unitree_sdk2/build/bin/g1_arm_action_example",
        help="Path to compiled official g1_arm_action_example binary",
    )
    parser.add_argument("--list-actions", action="store_true", help="Print supported mappings")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.list_actions:
        print(json.dumps([asdict(action) for action in ACTIONS], ensure_ascii=False, indent=2))
        return
    if not args.text:
        build_parser().error("the following arguments are required: text")

    if args.backend == "qwen":
        result = classify_qwen(
            args.text,
            args.qwen_model,
            args.qwen_base_url,
            args.threshold,
            keyword_first=not args.no_keyword_first,
        )
    elif args.backend == "hf":
        result = classify_hf(args.text, args.model, args.threshold)
    else:
        result = classify_keyword(args.text, args.threshold)

    execution: dict[str, Any]
    if args.execute:
        execution = execute_action(result, args.network, args.runner)
    elif result.action_id < 0:
        execution = {
            "executed": False,
            "reason": "dry_run_no_action",
            "would_run": [],
        }
    else:
        execution = {
            "executed": False,
            "reason": "dry_run",
            "would_run": [args.runner, "--network", args.network, "--id", str(result.action_id)],
        }

    print(json.dumps({"classification": asdict(result), "execution": execution}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
