import sqlite3
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SearchResult:
    id: int
    title: str
    content: str
    url: str
    category: str
    source_table: str
    source_id: int
    score: float


def init_vector_db(path: str) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            create table if not exists chunks (
                id integer primary key autoincrement,
                source_table text not null,
                source_id integer not null,
                title text not null,
                content text not null,
                url text not null,
                category text not null,
                embedding blob not null,
                dim integer not null,
                unique(source_table, source_id)
            )
            """
        )
        con.execute("create index if not exists idx_chunks_category on chunks(category)")
        con.commit()
    finally:
        con.close()


def reset_vector_db(path: str) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute("drop table if exists chunks")
        con.commit()
    finally:
        con.close()
    init_vector_db(path)


def vector_to_blob(vector: list[float]) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def blob_to_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def upsert_chunk(path: str, item, embedding: list[float]) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            insert into chunks(source_table, source_id, title, content, url, category, embedding, dim)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(source_table, source_id) do update set
                title=excluded.title,
                content=excluded.content,
                url=excluded.url,
                category=excluded.category,
                embedding=excluded.embedding,
                dim=excluded.dim
            """,
            (
                item.source_table,
                item.source_id,
                item.title,
                item.content,
                item.url,
                item.category,
                vector_to_blob(embedding),
                len(embedding),
            ),
        )
        con.commit()
    finally:
        con.close()


def search(path: str, query_embedding: list[float], top_k: int, threshold: float) -> list[SearchResult]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "select id, source_table, source_id, title, content, url, category, embedding from chunks"
        ).fetchall()
    finally:
        con.close()

    if not rows:
        return []

    query = np.asarray(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query)
    if query_norm == 0:
        return []

    scored: list[SearchResult] = []
    for row in rows:
        vector = blob_to_vector(row["embedding"])
        denom = query_norm * np.linalg.norm(vector)
        score = 0.0 if denom == 0 else float(np.dot(query, vector) / denom)
        if score >= threshold:
            scored.append(
                SearchResult(
                    id=row["id"],
                    title=row["title"],
                    content=row["content"],
                    url=row["url"],
                    category=row["category"],
                    source_table=row["source_table"],
                    source_id=row["source_id"],
                    score=score,
                )
            )

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]
