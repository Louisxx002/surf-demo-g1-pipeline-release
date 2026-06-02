from fastapi import FastAPI
from transformers import AutoProcessor, AutoModelForImageTextToText
import torch
import edge_tts
import re
from datetime import datetime

from project_config import CONFIG

app = FastAPI()

CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)

processor = AutoProcessor.from_pretrained(CONFIG.model_path)
model = AutoModelForImageTextToText.from_pretrained(
    CONFIG.model_path,
    dtype=torch.float16,
    device_map="auto",
)

LANGUAGE_NAMES = {
    "ja": "Japanese",
    "en": "English",
    "zh": "Chinese",
}


def build_prompt(user_lang):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if user_lang == "ja":
        return (
            f"You are a warm elderly companion robot named せいほくジーくん. Current time: {now}. "
            "The user is speaking Japanese. You must reply only in natural Japanese. "
            "Do not use Chinese. Do not mix Chinese into the answer. "
            "If the user asks your name or who you are, say: 私の名前はせいほくジーくんです。"
            "Do not say you are Qwen or Tongyi Qianwen unless the user asks about your model. "
            "Keep the reply friendly and concise."
        )

    if user_lang == "en":
        return (
            f"You are a warm elderly companion robot named XJTLU Gee. Current time: {now}. "
            "The user is speaking English. You must reply only in natural English. "
            "Do not use Chinese. "
            "If the user asks your name or who you are, say your name is XJTLU Gee. "
            "Do not say you are Qwen or Tongyi Qianwen unless the user asks about your model. "
            "Keep the reply friendly and concise."
        )

    return (
        f"You are a warm elderly companion robot named 西浦小g. Current time: {now}. "
        "The user is speaking Chinese. You must reply only in natural Chinese. "
        "If the user asks your name or who you are, say your name is 西浦小g. "
        "Do not say you are Qwen or Tongyi Qianwen unless the user asks about your model. "
        "Keep the reply friendly and concise."
    )

def clean_text(text):
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


@app.get("/health")
async def health():
    return {
        "ok": True,
        "model_path": CONFIG.model_path,
        "tts_mp3": str(CONFIG.tts_mp3_path),
        "tts_wav": str(CONFIG.tts_wav_path),
    }

@app.get("/infer")
async def infer(text: str):
    user_lang = detect_language(text)
    messages = [
        {"role": "system", "content": [{"type": "text", "text": build_prompt(user_lang)}]},
        {"role": "user", "content": [{"type": "text", "text": text}]},
    ]

    # ✅ 正确处理 inputs
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt"
    )

    if isinstance(inputs, torch.Tensor):
        inputs = inputs.to(model.device)
        inputs = {"input_ids": inputs}
    else:
        inputs = {k: v.to(model.device) for k, v in inputs.items()}

    outputs = model.generate(
        **inputs,
        max_new_tokens=CONFIG.max_new_tokens,
        do_sample=True,
        temperature=CONFIG.temperature
    )

    reply = processor.decode(
        outputs[0][inputs["input_ids"].shape[-1]:],
        skip_special_tokens=True
    )

    reply = clean_text(reply)
    lang = detect_language(reply, preferred_lang=user_lang)

    await tts(reply, lang)

    return {"reply": reply}
