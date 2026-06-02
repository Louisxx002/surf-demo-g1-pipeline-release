import argparse
import asyncio

from knowledge_extract import extract_items
from ollama_client import embed_text
from rag_config import settings
from vector_store import reset_vector_db, upsert_chunk


def build_embedding_text(item) -> str:
    return f"标题：{item.title}\n分类：{item.category}\n正文：{item.content}"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build local vector index from the XJTLU SQLite knowledge database.")
    parser.add_argument("--source-db", default=settings.source_db)
    parser.add_argument("--rag-db", default=settings.rag_db)
    parser.add_argument("--reset", action="store_true", help="Drop and rebuild the vector index.")
    args = parser.parse_args()

    if args.reset:
        reset_vector_db(args.rag_db)

    count = 0
    for item in extract_items(args.source_db):
        embedding = await embed_text(build_embedding_text(item))
        upsert_chunk(args.rag_db, item, embedding)
        count += 1
        if count % 25 == 0:
            print(f"indexed {count} chunks")

    print(f"done, indexed {count} chunks into {args.rag_db}")


if __name__ == "__main__":
    asyncio.run(main())
