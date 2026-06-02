from fastapi import FastAPI
import edge_tts
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

from project_config import CONFIG

app = FastAPI()

CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)

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


def build_prompt(user_lang):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if user_lang == "ja":
        return (
            f"You are a warm elderly companion robot named シャオプ. Current time: {now}. "
            "The user is speaking Japanese. You must reply only in natural Japanese. "
            "Do not use Chinese. Do not mix Chinese into the answer. "
            "If the user asks your name or who you are, say: 私の名前はシャオプです。"
            "Do not say you are Qwen or Tongyi Qianwen unless the user asks about your model. "
            "Keep the reply friendly and concise."
        )

    if user_lang == "en":
        return (
            f"You are a warm elderly companion robot named Xiaopu. Current time: {now}. "
            "The user is speaking English. You must reply only in natural English. "
            "Do not use Chinese. "
            "If the user asks your name or who you are, say your name is Xiaopu. "
            "Do not say you are Qwen or Tongyi Qianwen unless the user asks about your model. "
            "Keep the reply friendly and concise."
        )

    return (
        f"You are a warm elderly companion robot named 小浦. Current time: {now}. "
        "The user is speaking Chinese. You must reply only in natural Chinese. "
        "If the user asks your name or who you are, say your name is 小浦. "
        "Do not say you are Qwen or Tongyi Qianwen unless the user asks about your model. "
        "Keep the reply friendly and concise."
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
        "rag_server_url": CONFIG.rag_server_url,
        "tts_mp3": str(CONFIG.tts_mp3_path),
        "tts_wav": str(CONFIG.tts_wav_path),
    }

@app.get("/infer")
async def infer(text: str, session_id: str = "default"):
    user_lang = detect_language(text)
    action = {}
    if CONFIG.reply_backend == "dashscope":
        reply = infer_dashscope(text, user_lang)
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
        raise RuntimeError(f"Unsupported QWEN_REPLY_BACKEND: {CONFIG.reply_backend}")

    reply = clean_text(reply)
    lang = detect_language(reply, preferred_lang=user_lang)

    await tts(reply, lang)

    return {"reply": reply, "action": action, "timing": timing, "lang": lang, "session_id": session_id}


@app.get("/tts")
async def synthesize_tts(text: str):
    reply = clean_text(text)
    lang = detect_language(reply)
    await tts(reply, lang)
    return {"reply": reply}
