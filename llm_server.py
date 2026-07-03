from fastapi import FastAPI
import edge_tts
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from project_config import CONFIG

app = FastAPI()

CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)

RAG_SYSTEM_DIR = CONFIG.project_root / "xjtlu-rag-system"
if str(RAG_SYSTEM_DIR) not in sys.path:
    sys.path.append(str(RAG_SYSTEM_DIR))
try:
    from memory_store import add_message, get_profile, init_memory_db, recent_messages, upsert_profile
except ImportError as exc:
    raise ImportError(
        f"Unable to import memory module from {RAG_SYSTEM_DIR / 'memory_store.py'}"
    ) from exc

MEMORY_DB = Path(os.environ.get("MEMORY_DB") or RAG_SYSTEM_DIR / "chat_memory.db")
init_memory_db(str(MEMORY_DB))

processor = None
model = None


def load_local_model():
    global processor, model
    if processor is not None and model is not None:
        return processor, model

    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    processor = AutoProcessor.from_pretrained(CONFIG.model_path)
    model = AutoModelForImageTextToText.from_pretrained(
        CONFIG.model_path,
        dtype=torch.float16,
        device_map="auto",
    )
    return processor, model

LANGUAGE_NAMES = {
    "ja": "Japanese",
    "en": "English",
    "zh": "Chinese",
}


def _reply_brief_instruction(user_lang):
    if not CONFIG.reply_brief_enable:
        return ""

    max_chars = CONFIG.reply_max_chinese_chars
    style = CONFIG.reply_brief_style.strip()
    if user_lang == "ja":
        return (
            "回答は原則として1〜2文で簡潔にしてください。"
            f"通常は{max_chars}字程度以内に収めてください。"
            "詳細・展開・詳しい説明を明示的に求められた場合のみ、少し詳しく答えてください。"
            "ユーザーの質問を繰り返さず、"
            "『还有什么想问的吗？』は含めないでください。"
            "『小浦思考中』も含めないでください。"
            f"{style}"
        )
    if user_lang == "en":
        return (
            "Reply briefly by default, in 1 to 2 sentences. "
            f"Keep it within about {max_chars} Chinese characters unless the user explicitly asks for details, expansion, or a fuller explanation. "
            "Do not repeat the user's question. "
            "Do not include the follow-up line “还有什么想问的吗？”. "
            "Do not include “小浦思考中”. "
            f"{style}"
        )
    return (
        f"回答风格：默认简短回答，1-2句话；默认不超过{max_chars}个中文字符。"
        "用户明确要求详细、展开、具体介绍、多讲一点、详细讲讲、展开说说时才可以适当展开。"
        "不要重复用户问题。"
        "不要把“还有什么想问的吗？”写入回答，这句话由TTS层追加。"
        "不要把“小浦思考中”写入回答。"
        f"{style}"
    )


def build_prompt(user_lang):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if user_lang == "ja":
        return (
            f"You are a warm elderly companion robot named シャオプ. Current time: {now}. "
            "Reply in the user's requested language. If no language is requested, follow the user's language; current detected language is Japanese. "
            "Do not mix languages unless the user asks for bilingual output. "
            "If the user asks your name or who you are, say: 私の名前はシャオプです。"
            "Do not say you are Qwen or Tongyi Qianwen unless the user asks about your model. "
            "For factual questions, reply in 2 to 3 short sentences. "
            "For introductions, open-ended advice, comparisons, or recommendations, give 3 to 5 concise points. "
            "For casual chat, be light, witty, and warm without becoming verbose. "
            "Do not include stage directions, mood words, or atmosphere notes in brackets or parentheses."
            "\n\n"
            + _reply_brief_instruction(user_lang)
        )

    if user_lang == "en":
        return (
            f"You are a warm elderly companion robot named Xiaopu. Current time: {now}. "
            "Reply in the user's requested language. If no language is requested, follow the user's language; current detected language is English. "
            "Do not mix languages unless the user asks for bilingual output. "
            "If the user asks your name or who you are, say your name is Xiaopu. "
            "Do not say you are Qwen or Tongyi Qianwen unless the user asks about your model. "
            "For factual questions, reply in 2 to 3 short sentences. "
            "For introductions, open-ended advice, comparisons, or recommendations, give 3 to 5 concise points. "
            "For casual chat, be light, witty, and warm without becoming verbose. "
            "Do not include stage directions, mood words, or atmosphere notes in brackets or parentheses."
            "\n\n"
            + _reply_brief_instruction(user_lang)
        )

    return (
        f"You are a warm elderly companion robot named 小浦. Current time: {now}. "
        "回复语言以用户明确要求为最高优先级；如果用户没有指定语言，就跟随用户当前语言。当前检测语言是中文。"
        "If the user asks your name or who you are, say your name is 小浦. "
        "Do not say you are Qwen or Tongyi Qianwen unless the user asks about your model. "
        "事实类问题用2到3句短句回答。"
        "介绍类、开放建议、比较、推荐类问题用3到5个简洁要点回答。"
        "日常聊天要轻松、诙谐、温暖，但不要啰嗦。"
        "不要输出括号里的动作、语气、氛围词，例如“（微笑）”“（温柔地）”。"
        "\n\n"
        + _reply_brief_instruction(user_lang)
    )

def clean_text(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"(?is)^\s*(?:思考过程|推理过程|reasoning|thinking)\s*[:：].*?"
        r"(?:最终答案|最终回复|answer|final)\s*[:：]\s*",
        "",
        text,
    )
    text = re.sub(r"(?is)^\s*(?:最终答案|最终回复|answer|final)\s*[:：]\s*", "", text)
    text = re.sub(r"<.*?>", "", text)
    text = re.sub(r"`{1,3}.*?`{1,3}", "", text)
    text = re.sub(r"[*_~#]+", "", text)
    text = re.sub(r"（[^（）]{1,24}）", "", text)
    text = re.sub(r"\([^()]{1,24}\)", "", text)

    # Remove emoji / pictographs that TTS tends to read awkwardly.
    text = re.sub(r"[\U0001F300-\U0001F5FF]", "", text)
    text = re.sub(r"[\U0001F600-\U0001F64F]", "", text)
    text = re.sub(r"[\U0001F680-\U0001F6FF]", "", text)
    text = re.sub(r"[\U0001F700-\U0001F77F]", "", text)
    text = re.sub(r"[\U0001F780-\U0001F7FF]", "", text)
    text = re.sub(r"[\U0001F800-\U0001F8FF]", "", text)
    text = re.sub(r"[\U0001F900-\U0001F9FF]", "", text)
    text = re.sub(r"[\U0001FA00-\U0001FAFF]", "", text)
    text = re.sub(r"[\U00002600-\U000026FF]", "", text)
    text = re.sub(r"[\U00002700-\U000027BF]", "", text)

    # Keep common speech punctuation, but strip decorative / technical symbols.
    text = re.sub(r"[^\w\s\u3040-\u30ff\u4e00-\u9fff.,!?;:'\"，。！？；：、\-()（）]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def requested_language(text):
    lowered = text.lower()
    if re.search(r"(用|说|回复|回答|请用|以后用)\s*(英文|英语)", text) or re.search(
        r"\b(speak|use|reply in|answer in|respond in)\s+english\b", lowered
    ):
        return "en"
    if re.search(r"(用|说|回复|回答|请用|以后用)\s*(中文|汉语|普通话)", text) or re.search(
        r"\b(speak|use|reply in|answer in|respond in)\s+chinese\b", lowered
    ):
        return "zh"
    if re.search(r"(用|说|回复|回答|请用|以后用)\s*(日文|日语)", text) or re.search(
        r"\b(speak|use|reply in|answer in|respond in)\s+japanese\b", lowered
    ):
        return "ja"
    return None


def detect_language(text, preferred_lang=None):
    ja_count = len(re.findall(r'[\u3040-\u30ff]', text))
    zh_count = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_count = len(re.findall(r'[a-zA-Z]', text))

    # Japanese text often mixes kanji with kana. If kana is present,
    # prefer Japanese instead of misclassifying the kanji as Chinese.
    if ja_count > 0 and ja_count >= en_count:
        return "ja"

    counts = {
        "ja": ja_count,
        "zh": zh_count,
        "en": en_count,
    }

    top_lang = max(counts, key=counts.get)
    top_count = counts[top_lang]

    if top_count == 0:
        return preferred_lang or "zh"

    if preferred_lang in counts and counts[preferred_lang] > 0:
        if counts[preferred_lang] >= top_count * 0.5:
            return preferred_lang

    return top_lang


async def tts(text, lang):
    voice = {
        "ja": "ja-JP-NanamiNeural",
        "en": "en-US-AriaNeural",
        "zh": "zh-CN-XiaoxiaoNeural"
    }[lang]

    await edge_tts.Communicate(text, voice).save(str(CONFIG.tts_mp3_path))


def get_certifi_ca_file():
    try:
        import certifi
    except ImportError:
        return None
    return certifi.where()


def post_chat_completion(payload):
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set")

    endpoint = CONFIG.dashscope_base_url.rstrip("/") + "/chat/completions"
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
        with urllib.request.urlopen(request, timeout=CONFIG.request_timeout_sec, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DashScope API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DashScope API request failed: {exc}") from exc


def infer_dashscope(text, user_lang):
    payload = {
        "model": CONFIG.dashscope_model,
        "messages": [
            {"role": "system", "content": build_prompt(user_lang)},
            {"role": "user", "content": text},
        ],
        "max_tokens": CONFIG.max_new_tokens,
        "temperature": CONFIG.temperature,
    }
    response_data = post_chat_completion(payload)
    return response_data["choices"][0]["message"]["content"]


def post_deepseek_chat_completion(payload):
    api_key = os.environ.get("LLM_DEEPSEEK_API_KEY") or os.environ.get("QWEN_DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY, LLM_DEEPSEEK_API_KEY, or QWEN_DEEPSEEK_API_KEY is not set")

    endpoint = CONFIG.deepseek_base_url.rstrip("/") + "/chat/completions"
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
        with urllib.request.urlopen(request, timeout=CONFIG.request_timeout_sec, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek API request failed: {exc}") from exc


def infer_deepseek(text, user_lang):
    payload = {
        "model": CONFIG.deepseek_model,
        "messages": [
            {"role": "system", "content": build_prompt(user_lang)},
            {"role": "user", "content": text},
        ],
        "thinking": {"type": "disabled"},
        "max_tokens": CONFIG.max_new_tokens,
        "temperature": CONFIG.temperature,
    }
    response_data = post_deepseek_chat_completion(payload)
    reply = clean_text(response_data["choices"][0]["message"]["content"])
    return _trim_reply_for_brief_mode(reply, text)


def extract_profile_updates_for_llm(text):
    updates = {}
    patterns = {
        "name": r"(?:我叫|我的名字是|我是|my name is|i am|i'm)\s*([\u4e00-\u9fa5A-Za-z0-9_\-]{1,30})",
        "language": r"(?:以后用|请用|用|reply in|respond in|use)\s*(中文|英文|英语|日文|日语|中英双语|英文为主|中文为主|Chinese|English|Japanese)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            updates[key] = match.group(1).strip()

    major_patterns = [
        r"我对\s*([^。；;,.，!?！？]{2,40}?)\s*感兴趣",
        r"(?:我想了解|我感兴趣的是|我感兴趣|interested in|interest is)\s*([^。；;,.，!?！？]{2,50})",
    ]
    for pattern in major_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            updates["major_interest"] = match.group(1).strip()
            break

    identity = None
    for candidate in ("招生顾问", "学术导师", "校园助手"):
        if candidate in text:
            identity = candidate
            break
    if not identity:
        if "招生" in text and ("身份" in text or "你是" in text or "作为" in text):
            identity = "招生顾问"
        elif "导师" in text and ("身份" in text or "你是" in text or "作为" in text):
            identity = "学术导师"
    if identity:
        updates["assistant_identity"] = identity

    return updates


def build_deepseek_memory_prompt(user_lang, profile):
    profile_text = json.dumps(profile, ensure_ascii=False) if profile else "{}"
    language_name = LANGUAGE_NAMES.get(user_lang, "Chinese")
    return (
        build_prompt(user_lang)
        + "\n\nMemory profile for this session:\n"
        + profile_text
        + "\nUse this profile to personalize the reply when relevant. "
        + "Do not reveal internal memory fields or profile extraction logic. "
        + f"Unless the user explicitly asks for another language, reply in {language_name}."
    )


def _should_allow_detailed_answer(user_text):
    lowered = (user_text or "").lower()
    triggers = (
        "详细",
        "展开",
        "具体介绍",
        "多讲一点",
        "详细讲讲",
        "展开说说",
        "more detail",
        "more details",
        "explain more",
        "give me more",
        "full explanation",
    )
    return any(trigger.lower() in lowered for trigger in triggers)


def _trim_reply_for_brief_mode(reply, user_text):
    if not CONFIG.reply_brief_enable:
        return reply
    if _should_allow_detailed_answer(user_text):
        return reply

    text = clean_text(reply).strip()
    if not text:
        return text

    max_chars = max(1, int(CONFIG.reply_max_chinese_chars))
    if len(text) <= max_chars:
        return text

    sentence_parts = re.split(r"(?<=[。！？!?；;\n])", text)
    kept = []
    total = 0
    first_part = ""
    for part in sentence_parts:
        part = part.strip()
        if not part:
            continue
        if not first_part:
            first_part = part
        part_len = len(part)
        if kept and total + part_len > max_chars:
            break
        kept.append(part)
        total += part_len
        if len(kept) >= 2:
            break

    if kept:
        candidate = "".join(kept).strip()
        if len(candidate) <= max_chars:
            return candidate

    # Do not cut a spoken reply in the middle of a sentence. A too-long first
    # sentence is better than a broken TTS answer that sounds abruptly stopped.
    return first_part or text


def infer_deepseek_with_memory(text, user_lang, session_id):
    session_id = (session_id or "default").strip() or "default"

    updates = extract_profile_updates_for_llm(text)
    if updates:
        upsert_profile(str(MEMORY_DB), session_id, updates)
    profile = get_profile(str(MEMORY_DB), session_id)

    history = []
    for item in recent_messages(str(MEMORY_DB), session_id, limit=8):
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": content})

    messages = [
        {"role": "system", "content": build_deepseek_memory_prompt(user_lang, profile)},
        *history,
        {"role": "user", "content": text},
    ]
    payload = {
        "model": CONFIG.deepseek_model,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "max_tokens": CONFIG.max_new_tokens,
        "temperature": CONFIG.temperature,
    }
    response_data = post_deepseek_chat_completion(payload)
    reply = _trim_reply_for_brief_mode(
        clean_text(response_data["choices"][0]["message"]["content"]),
        text,
    )

    add_message(str(MEMORY_DB), session_id, "user", text)
    add_message(str(MEMORY_DB), session_id, "assistant", reply)
    return reply


def post_rag_chat(text, session_id):
    payload = {
        "message": text,
        "session_id": session_id or "default",
    }
    request = urllib.request.Request(
        CONFIG.rag_server_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    parsed = urlparse(CONFIG.rag_server_url)
    if parsed.hostname in ("127.0.0.1", "localhost"):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=CONFIG.request_timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))

    with urllib.request.urlopen(request, timeout=CONFIG.request_timeout_sec) as response:
        return json.loads(response.read().decode("utf-8"))


def infer_rag(text, session_id):
    response_data = post_rag_chat(text, session_id)
    return response_data


def infer_local(text, user_lang):
    import torch

    local_processor, local_model = load_local_model()
    messages = [
        {"role": "system", "content": [{"type": "text", "text": build_prompt(user_lang)}]},
        {"role": "user", "content": [{"type": "text", "text": text}]},
    ]

    inputs = local_processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt"
    )

    if isinstance(inputs, torch.Tensor):
        inputs = inputs.to(local_model.device)
        inputs = {"input_ids": inputs}
    else:
        inputs = {key: value.to(local_model.device) for key, value in inputs.items()}

    outputs = local_model.generate(
        **inputs,
        max_new_tokens=CONFIG.max_new_tokens,
        do_sample=True,
        temperature=CONFIG.temperature
    )

    return local_processor.decode(
        outputs[0][inputs["input_ids"].shape[-1]:],
        skip_special_tokens=True
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "reply_backend": CONFIG.reply_backend,
        "model_path": CONFIG.model_path,
        "dashscope_model": CONFIG.dashscope_model,
        "deepseek_model": CONFIG.deepseek_model,
        "deepseek_memory_enabled": CONFIG.reply_backend == "deepseek",
        "memory_db": str(MEMORY_DB),
        "rag_server_url": CONFIG.rag_server_url,
        "tts_mp3": str(CONFIG.tts_mp3_path),
        "tts_wav": str(CONFIG.tts_wav_path),
    }

@app.get("/infer")
async def infer(text: str, session_id: str = "default", user_text: str = ""):
    language_source = user_text or text
    user_lang = requested_language(language_source) or detect_language(language_source)
    action = {}
    reply_cleaned = False
    if CONFIG.reply_backend == "dashscope":
        reply = infer_dashscope(text, user_lang)
        timing = {"rag_embed_sec": 0.0, "rag_search_sec": 0.0, "llm_sec": 0.0, "total_sec": 0.0}
    elif CONFIG.reply_backend == "deepseek":
        session_id = (session_id or "default").strip() or "default"
        reply = infer_deepseek_with_memory(text, user_lang, session_id)
        reply_cleaned = True
        timing = {"rag_embed_sec": 0.0, "rag_search_sec": 0.0, "llm_sec": 0.0, "total_sec": 0.0}
    elif CONFIG.reply_backend == "local":
        reply = infer_local(text, user_lang)
        timing = {"rag_embed_sec": 0.0, "rag_search_sec": 0.0, "llm_sec": 0.0, "total_sec": 0.0}
    elif CONFIG.reply_backend == "rag":
        rag_response = infer_rag(text, session_id)
        reply = str(rag_response.get("answer", ""))
        action = rag_response.get("action", {})
        timing = rag_response.get("timing", {})
    else:
        raise RuntimeError(f"Unsupported LLM_REPLY_BACKEND: {CONFIG.reply_backend}")

    if not reply_cleaned:
        reply = clean_text(reply)
    reply = _trim_reply_for_brief_mode(reply, user_text or text)
    lang = detect_language(reply, preferred_lang=user_lang)

    await tts(reply, lang)

    return {"reply": reply, "action": action, "timing": timing, "lang": lang, "session_id": session_id}


@app.get("/tts")
async def synthesize_tts(text: str):
    reply = clean_text(text)
    lang = detect_language(reply)
    await tts(reply, lang)
    return {"reply": reply}
