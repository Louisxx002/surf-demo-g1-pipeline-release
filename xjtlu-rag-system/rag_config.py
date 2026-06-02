import os
from dataclasses import dataclass


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    source_db: str = _env("SOURCE_DB", "./xjtlu_knowledge.db")
    rag_db: str = _env("RAG_DB", "./rag_index.db")
    memory_db: str = _env("MEMORY_DB", "./chat_memory.db")
    chat_provider: str = _env("CHAT_PROVIDER", "openai").lower()
    embed_provider: str = _env("EMBED_PROVIDER", "ollama").lower()
    ollama_base_url: str = _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    openai_base_url: str = _env("OPENAI_BASE_URL", "https://api.deepseek.com").rstrip("/")
    openai_api_key: str = _env("OPENAI_API_KEY", "EMPTY")
    embed_model: str = _env("EMBED_MODEL", "nomic-embed-text")
    chat_model: str = _env("CHAT_MODEL", "deepseek-v4-pro")
    top_k: int = int(_env("TOP_K", "10"))
    similarity_threshold: float = float(_env("SIMILARITY_THRESHOLD", "0.35"))


settings = Settings()
