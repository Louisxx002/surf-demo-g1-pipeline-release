import json
import sqlite3
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_memory_db(path: str) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            create table if not exists user_profile (
                session_id text not null,
                key text not null,
                value text not null,
                updated_at text not null,
                primary key(session_id, key)
            )
            """
        )
        con.execute(
            """
            create table if not exists messages (
                id integer primary key autoincrement,
                session_id text not null,
                role text not null,
                content text not null,
                created_at text not null
            )
            """
        )
        con.commit()
    finally:
        con.close()


def get_profile(path: str, session_id: str) -> dict[str, str]:
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            "select key, value from user_profile where session_id = ? order by key",
            (session_id,),
        ).fetchall()
    finally:
        con.close()
    return {key: value for key, value in rows}


def upsert_profile(path: str, session_id: str, updates: dict[str, str]) -> None:
    if not updates:
        return
    con = sqlite3.connect(path)
    try:
        for key, value in updates.items():
            con.execute(
                """
                insert into user_profile(session_id, key, value, updated_at)
                values (?, ?, ?, ?)
                on conflict(session_id, key) do update set
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (session_id, key.strip(), value.strip(), utc_now()),
            )
        con.commit()
    finally:
        con.close()


def add_message(path: str, session_id: str, role: str, content: str) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(
            "insert into messages(session_id, role, content, created_at) values (?, ?, ?, ?)",
            (session_id, role, content, utc_now()),
        )
        con.commit()
    finally:
        con.close()


def recent_messages(path: str, session_id: str, limit: int = 8) -> list[dict[str, str]]:
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            """
            select role, content from messages
            where session_id = ?
            order by id desc
            limit ?
            """,
            (session_id, limit),
        ).fetchall()
    finally:
        con.close()
    return [{"role": role, "content": content} for role, content in reversed(rows)]


def export_session(path: str, session_id: str) -> str:
    return json.dumps(
        {
            "profile": get_profile(path, session_id),
            "messages": recent_messages(path, session_id, 50),
        },
        ensure_ascii=False,
        indent=2,
    )
