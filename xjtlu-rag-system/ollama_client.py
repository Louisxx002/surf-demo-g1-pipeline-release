import httpx
import re

from rag_config import settings


def strip_reasoning_text(text: str) -> str:
    """Remove DeepSeek reasoning traces before returning user-visible text."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"(?is)^\s*(?:思考过程|推理过程|reasoning|thinking)\s*[:：].*?"
        r"(?:最终答案|最终回复|answer|final)\s*[:：]\s*",
        "",
        text,
    )
    text = re.sub(r"(?is)^\s*(?:最终答案|最终回复|answer|final)\s*[:：]\s*", "", text)
    return text.strip()


async def _ollama_embed(text: str) -> list[float]:
    payload = {"model": settings.embed_model, "input": text}
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        response = await client.post(f"{settings.ollama_base_url}/api/embed", json=payload)
        if response.status_code == 404:
            response = await client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json={"model": settings.embed_model, "prompt": text},
            )
        response.raise_for_status()
        data = response.json()
    if "embedding" in data:
        return data["embedding"]
    return data["embeddings"][0]


async def _openai_embed(text: str) -> list[float]:
    payload = {"model": settings.embed_model, "input": text}
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        response = await client.post(f"{settings.openai_base_url}/embeddings", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    return data["data"][0]["embedding"]


async def embed_text(text: str) -> list[float]:
    if settings.embed_provider == "openai":
        return await _openai_embed(text)
    return await _ollama_embed(text)


async def _ollama_generate(prompt: str, system: str | None = None) -> str:
    payload = {
        "model": settings.chat_model,
        "prompt": prompt,
        "system": system or "",
        "stream": False,
        "options": {
            "temperature": 0.3,
            "top_p": 0.9,
        },
    }
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        response = await client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
        response.raise_for_status()
        data = response.json()
    return strip_reasoning_text(data.get("response", ""))


async def _openai_generate(prompt: str, system: str | None = None) -> str:
    payload = {
        "model": settings.chat_model,
        "messages": [
            {"role": "system", "content": system or ""},
            {"role": "user", "content": prompt},
        ],
        "thinking": {"type": "disabled"},
        "temperature": 0.3,
        "top_p": 0.9,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        response = await client.post(f"{settings.openai_base_url}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    message = data["choices"][0]["message"]
    return strip_reasoning_text(message.get("content") or "")


async def generate_text(prompt: str, system: str | None = None) -> str:
    if settings.chat_provider == "openai":
        return await _openai_generate(prompt, system)
    return await _ollama_generate(prompt, system)
