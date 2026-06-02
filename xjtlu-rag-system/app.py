from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from chat_engine import chat
from memory_store import export_session, init_memory_db
from rag_config import settings
from vector_store import init_vector_db


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = "default"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_vector_db(settings.rag_db)
    init_memory_db(settings.memory_db)
    yield


app = FastAPI(title="XJTLU Chinese Local RAG", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", "r", encoding="utf-8") as file:
        return file.read()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "rag_db": settings.rag_db,
        "memory_db": settings.memory_db,
        "embed_model": settings.embed_model,
        "chat_model": settings.chat_model,
    }


@app.post("/chat")
async def chat_api(request: ChatRequest):
    return await chat(request.session_id, request.message)


@app.get("/profile/{session_id}")
async def profile(session_id: str):
    return {"session_id": session_id, "data": export_session(settings.memory_db, session_id)}
