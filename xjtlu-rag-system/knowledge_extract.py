import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeItem:
    source_table: str
    source_id: int
    title: str
    content: str
    url: str
    category: str


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def extract_items(source_db: str) -> Iterable[KnowledgeItem]:
    con = sqlite3.connect(source_db)
    con.row_factory = sqlite3.Row
    try:
        for row in con.execute(
            """
            select
                dc.id as source_id,
                d.title,
                dc.chunk_text as content,
                d.url,
                d.category
            from document_chunks dc
            join documents d on d.id = dc.document_id
            where length(trim(dc.chunk_text)) > 0
            order by dc.id
            """
        ):
            yield KnowledgeItem(
                source_table="document_chunks",
                source_id=row["source_id"],
                title=_clean(row["title"]),
                content=_clean(row["content"]),
                url=_clean(row["url"]),
                category=_clean(row["category"]),
            )

        for row in con.execute("select id, question, answer, category, source_url from faq order by id"):
            yield KnowledgeItem(
                source_table="faq",
                source_id=row["id"],
                title=_clean(row["question"]),
                content=f"问题：{_clean(row['question'])}\n回答：{_clean(row['answer'])}",
                url=_clean(row["source_url"]),
                category=_clean(row["category"]),
            )

        for row in con.execute(
            "select id, programme_name, degree, duration, school, location, description, source_url from programmes order by id"
        ):
            title = f"{_clean(row['degree'])} {_clean(row['programme_name'])}".strip()
            content = "\n".join(
                part
                for part in [
                    f"专业：{_clean(row['programme_name'])}",
                    f"学位：{_clean(row['degree'])}",
                    f"学制：{_clean(row['duration'])}",
                    f"学院：{_clean(row['school'])}",
                    f"地点：{_clean(row['location'])}",
                    f"介绍：{_clean(row['description'])}",
                ]
                if part
            )
            yield KnowledgeItem(
                source_table="programmes",
                source_id=row["id"],
                title=title,
                content=content,
                url=_clean(row["source_url"]),
                category="programmes",
            )

        for row in con.execute("select id, title, content, category, source_url from school_info order by id"):
            yield KnowledgeItem(
                source_table="school_info",
                source_id=row["id"],
                title=_clean(row["title"]),
                content=_clean(row["content"]),
                url=_clean(row["source_url"]),
                category=_clean(row["category"]),
            )

        for row in con.execute("select id, school_name, department_name, description, source_url from departments order by id"):
            title = " - ".join(part for part in [_clean(row["school_name"]), _clean(row["department_name"])] if part)
            yield KnowledgeItem(
                source_table="departments",
                source_id=row["id"],
                title=title,
                content=_clean(row["description"]),
                url=_clean(row["source_url"]),
                category="departments",
            )

        for row in con.execute("select id, year, event_title, event_description, source_url from events order by id"):
            yield KnowledgeItem(
                source_table="events",
                source_id=row["id"],
                title=f"{_clean(row['year'])} {_clean(row['event_title'])}",
                content=_clean(row["event_description"]),
                url=_clean(row["source_url"]),
                category="events",
            )
    finally:
        con.close()
