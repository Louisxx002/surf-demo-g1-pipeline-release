"""
服务器连接测试脚本
用于测试与远程 Qwen3VL-4B 服务器的连接
"""

import asyncio
import sys
import httpx
from rag_config import settings


async def test_connection():
    print("=" * 60)
    print("  XJTLU RAG - 服务器连接测试")
    print("=" * 60)
    print()
    
    errors = []
    
    # 测试 1: Embedding API
    print("[测试 1] 连接 Embedding 服务...")
    print(f"  URL: {settings.openai_base_url}/embeddings")
    print(f"  模型: {settings.embed_model}")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{settings.openai_base_url}/embeddings",
                json={"model": settings.embed_model, "input": "这是一条测试文本"},
                headers={"Authorization": f"Bearer {settings.openai_api_key}"}
            )
            if response.status_code == 200:
                data = response.json()
                embed_dim = len(data["data"][0]["embedding"])
                print(f"  ✓ 连接成功! 向量维度: {embed_dim}")
            else:
                errors.append(f"Embedding API 返回状态码: {response.status_code}")
                print(f"  ✗ 失败: {response.status_code} - {response.text}")
    except Exception as e:
        errors.append(f"Embedding 连接错误: {str(e)}")
        print(f"  ✗ 连接失败: {e}")
    
    # 测试 2: Chat API
    print()
    print("[测试 2] 连接 Chat 服务...")
    print(f"  URL: {settings.openai_base_url}/chat/completions")
    print(f"  模型: {settings.chat_model}")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{settings.openai_base_url}/chat/completions",
                json={
                    "model": settings.chat_model,
                    "messages": [
                        {"role": "system", "content": "你是一个测试助手"},
                        {"role": "user", "content": "你好，请回复 '测试成功'"}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 100
                },
                headers={"Authorization": f"Bearer {settings.openai_api_key}"}
            )
            if response.status_code == 200:
                data = response.json()
                answer = data["choices"][0]["message"]["content"]
                print(f"  ✓ 连接成功!")
                print(f"  模型回复: {answer}")
            else:
                errors.append(f"Chat API 返回状态码: {response.status_code}")
                print(f"  ✗ 失败: {response.status_code} - {response.text}")
    except Exception as e:
        errors.append(f"Chat 连接错误: {str(e)}")
        print(f"  ✗ 连接失败: {e}")
    
    # 测试 3: 本地数据库
    print()
    print("[测试 3] 检查本地数据库...")
    import sqlite3
    import os
    
    # 检查源数据库
    if os.path.exists(settings.source_db):
        try:
            con = sqlite3.connect(settings.source_db)
            cur = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            tables = [t[0] for t in cur]
            con.close()
            print(f"  ✓ 知识库数据库存在: {settings.source_db}")
            print(f"  表: {', '.join(tables)}")
        except Exception as e:
            errors.append(f"知识库数据库错误: {str(e)}")
            print(f"  ✗ 读取失败: {e}")
    else:
        errors.append(f"知识库数据库不存在: {settings.source_db}")
        print(f"  ✗ 文件不存在: {settings.source_db}")
    
    # 检查向量数据库
    if os.path.exists(settings.rag_db):
        try:
            con = sqlite3.connect(settings.rag_db)
            count = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            con.close()
            print(f"  ✓ 向量索引存在: {settings.rag_db}")
            print(f"  索引块数: {count}")
        except Exception as e:
            print(f"  ! 向量索引可能未构建: {e}")
    else:
        print(f"  ! 向量索引不存在，将在使用时自动构建")
    
    # 总结
    print()
    print("=" * 60)
    if errors:
        print("  ⚠️  发现问题:")
        for err in errors:
            print(f"    - {err}")
        print()
        print("  解决方案:")
        print("    1. 检查远程服务器是否启动")
        print("    2. 确认 .env 中的服务器地址正确")
        print("    3. 检查服务器防火墙是否放行端口")
        print("    4. 确认模型名称与服务器配置一致")
    else:
        print("  ✓ 所有测试通过!")
    print("=" * 60)
    
    return len(errors) == 0


if __name__ == "__main__":
    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)
