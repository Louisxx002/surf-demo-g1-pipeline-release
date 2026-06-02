import json
import os
import re
import time

import sqlite3
from dataclasses import asdict, dataclass

from memory_store import add_message, get_profile, recent_messages, upsert_profile
from ollama_client import embed_text, generate_text
from rag_config import settings
from vector_store import SearchResult, search


ANSWER_MAX_CHARS = int(os.getenv("ANSWER_MAX_CHARS", "100"))


@dataclass(frozen=True)
class ArmAction:
    label: str
    official_name: str
    action_id: int


ACTIONS: tuple[ArmAction, ...] = (
    ArmAction("无动作", "none", -1),
    ArmAction("释放手臂", "release arm", 99),
    ArmAction("双手飞吻", "two-hand kiss", 11),
    ArmAction("右手飞吻", "right kiss", 13),
    ArmAction("左手飞吻", "left kiss", 12),
    ArmAction("举双手", "hands up", 15),
    ArmAction("鼓掌", "clap", 17),
    ArmAction("击掌", "high five", 18),
    ArmAction("拥抱", "hug", 19),
    ArmAction("比心", "heart", 20),
    ArmAction("右手比心", "right heart", 21),
    ArmAction("拒绝摆手", "reject", 22),
    ArmAction("举右手", "right hand up", 23),
    ArmAction("x-ray", "x-ray", 24),
    ArmAction("面前挥手", "face wave", 25),
    ArmAction("高位挥手", "high wave", 26),
    ArmAction("握手", "shake hand", 27),
)


def _find_action(label: str) -> ArmAction:
    for action in ACTIONS:
        if action.label == label:
            return action
    return ACTIONS[0]


def _default_action(reason: str = "DeepSeek did not provide a valid action.") -> dict:
    action = ACTIONS[0]
    return {
        "label": action.label,
        "official_name": action.official_name,
        "action_id": action.action_id,
        "score": 0.0,
        "backend": "deepseek",
        "reason": reason,
    }


def _parse_json_object(content: str) -> dict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            return {"answer": content, "action": _default_action("DeepSeek returned plain text.")}
        parsed = json.loads(match.group(0))
    return parsed if isinstance(parsed, dict) else {"answer": content, "action": _default_action()}


def _normalize_action(payload: object) -> dict:
    if not isinstance(payload, dict):
        return _default_action()

    action = _find_action(str(payload.get("label", "无动作")).strip())
    try:
        score = float(payload.get("score", payload.get("confidence", 0.0)))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))

    return {
        "label": action.label,
        "official_name": action.official_name,
        "action_id": action.action_id,
        "score": score,
        "backend": "deepseek",
        "reason": str(payload.get("reason", "")).strip(),
    }


def _limit_answer(answer: str, max_chars: int = ANSWER_MAX_CHARS) -> str:
    answer = answer.strip()
    if max_chars <= 0 or len(answer) <= max_chars:
        return answer

    truncated = answer[:max_chars]
    for mark in ["。", "！", "？", "\n"]:
        pos = truncated.rfind(mark)
        if pos >= max_chars * 0.55:
            return truncated[: pos + 1].strip()
    return truncated[: max_chars - 3].rstrip() + "..."


def _is_programme_query(message: str) -> bool:
    """Detect if the query is about programmes/majors."""
    keywords = ["专业", "有哪些", "有什么专业", "有哪些专业", "多少专业", "总共有多少", "专业列表", "专业一览"]
    return any(kw in message for kw in keywords)


def _build_programme_context(message: str, source_db: str) -> str:
    """Return a structured programme list for programme-related queries."""
    if not _is_programme_query(message):
        return ""
    try:
        conn = sqlite3.connect(source_db)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT programme_name, degree, school, location
            FROM programmes
            ORDER BY school, degree, programme_name
        """)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return ""

        degree_map = {
            "BEng (Hons)": "工学学士", "BSc (Hons)": "理学学士", "BA (Hons)": "文学学士",
            "MSc": "理学硕士", "MA": "文学硕士", "MPhil": "研究型硕士",
            "PhD": "博士", "MBA": "工商管理硕士", "MA/MSc": "文学/理学硕士", "EdD": "教育学博士",
        }

        school_map = {}
        for row in rows:
            school = row["school"]
            if school not in school_map:
                school_map[school] = {"undergrad": [], "postgrad": []}
            deg_cn = degree_map.get(row["degree"], row["degree"])
            prog_line = f"{row['programme_name']}（{deg_cn}）"
            if "(Hons)" in row["degree"]:
                school_map[school]["undergrad"].append(prog_line)
            else:
                school_map[school]["postgrad"].append(prog_line)

        lines = []
        for school, groups in school_map.items():
            parts = [f"【{school}】"]
            if groups["undergrad"]:
                undergrad_str = "、".join(groups["undergrad"])
                parts.append(f"  本科：{undergrad_str}")
            if groups["postgrad"]:
                postgrad_str = "、".join(groups["postgrad"])
                parts.append(f"  硕士/博士：{postgrad_str}")
            lines.append("\n".join(parts))

        total = len(rows)
        header = f"以下是西交利物浦大学的全部{total}个专业的完整列表（按学院分类）：\n\n"
        return header + "\n\n".join(lines)
    except Exception:
        return ""


def _build_direct_faq_context(message: str, source_db: str) -> str:
    """Return exact FAQ facts for high-confidence basic-information queries."""
    location_terms = ["在哪里", "在哪", "地址", "位置", "校区", "在西安"]
    credential_terms = ["证书", "毕业证", "学位证", "学位", "学历", "毕业后可以获得"]
    admission_terms = ["本科如何招生", "如何招生", "怎么招生", "高考生如何报考", "如何报考", "怎么报考", "本科招生"]
    transfer_terms = ["转专业", "转换专业", "换专业", "专业选择"]
    duration_terms = ["读几年", "几年", "学制", "本科一般读", "本科读"]
    pathway_terms = ["2+2", "4+0", "4+X", "2+1+1", "必须去英国", "不去英国", "利物浦大学学习"]
    is_location_query = any(term in message for term in location_terms)
    is_credential_query = any(term in message for term in credential_terms)
    is_admission_query = any(term in message for term in admission_terms)
    is_transfer_query = any(term in message for term in transfer_terms)
    is_duration_query = any(term in message for term in duration_terms)
    is_pathway_query = any(term in message for term in pathway_terms)
    if (
        not is_location_query
        and not is_credential_query
        and not is_admission_query
        and not is_transfer_query
        and not is_duration_query
        and not is_pathway_query
    ):
        return ""

    try:
        conn = sqlite3.connect(source_db)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if is_location_query:
            rows = cur.execute(
                """
                SELECT question, answer, category, source_url
                FROM faq
                WHERE question LIKE '%哪里%'
                   OR question LIKE '%地址%'
                   OR answer LIKE '%仁爱路111号%'
                   OR answer LIKE '%太仓大道111号%'
                ORDER BY
                    CASE
                        WHEN question LIKE '%在哪里%' THEN 0
                        WHEN question LIKE '%校园在哪里%' THEN 1
                        ELSE 2
                    END,
                    id
                LIMIT 4
                """
            ).fetchall()
        elif is_credential_query:
            rows = cur.execute(
                """
                SELECT question, answer, category, source_url
                FROM faq
                WHERE question LIKE '%证书%'
                   OR question LIKE '%学位%'
                   OR answer LIKE '%毕业证书%'
                   OR answer LIKE '%学士学位证书%'
                   OR answer LIKE '%利物浦大学%学位%'
                ORDER BY
                    CASE
                        WHEN question LIKE '%获得哪些证书%' THEN 0
                        WHEN question LIKE '%本科毕业%' THEN 1
                        WHEN question LIKE '%研究生毕业%' THEN 2
                        ELSE 3
                    END,
                    id
                LIMIT 5
                """
            ).fetchall()
        elif is_admission_query:
            rows = cur.execute(
                """
                SELECT question, answer, category, source_url
                FROM faq
                WHERE question LIKE '%本科如何招生%'
                   OR question LIKE '%高考生如何报考%'
                   OR question LIKE '%如何报考%'
                   OR answer LIKE '%高考选拔招生%'
                   OR answer LIKE '%综合评价录取%'
                   OR answer LIKE '%面向全国统一招收本科学生%'
                ORDER BY
                    CASE
                        WHEN question LIKE '%本科如何招生%' THEN 0
                        WHEN question LIKE '%高考生如何报考%' THEN 1
                        WHEN question LIKE '%如何报考%' THEN 2
                        ELSE 3
                    END,
                    id
                LIMIT 5
                """
            ).fetchall()
        elif is_transfer_query:
            rows = cur.execute(
                """
                SELECT question, answer, category, source_url
                FROM faq
                WHERE question LIKE '%转专业%'
                   OR question LIKE '%专业选择%'
                   OR answer LIKE '%专业选择和转专业政策%'
                   OR answer LIKE '%大类招生政策%'
                   OR answer LIKE '%以兴趣为导向%'
                ORDER BY
                    CASE
                        WHEN question LIKE '%转专业%' THEN 0
                        WHEN question LIKE '%专业选择%' THEN 1
                        ELSE 2
                    END,
                    id
                LIMIT 5
                """
            ).fetchall()
        elif is_duration_query:
            rows = cur.execute(
                """
                SELECT question, answer, category, source_url
                FROM faq
                WHERE question LIKE '%读几年%'
                   OR question LIKE '%学制%'
                   OR answer LIKE '%本科%四年%'
                   OR answer LIKE '%学制为四年%'
                ORDER BY
                    CASE
                        WHEN question LIKE '%本科一般读几年%' THEN 0
                        WHEN question LIKE '%学制%' THEN 1
                        ELSE 2
                    END,
                    id
                LIMIT 5
                """
            ).fetchall()
        else:
            rows = cur.execute(
                """
                SELECT question, answer, category, source_url
                FROM faq
                WHERE question LIKE '%2+2%'
                   OR question LIKE '%4+0%'
                   OR question LIKE '%必须去英国%'
                   OR question LIKE '%不去英国%'
                   OR answer LIKE '%前两年在西交利物浦大学%'
                   OR answer LIKE '%后两年在英国利物浦大学%'
                   OR answer LIKE '%四年都在西交利物浦大学%'
                ORDER BY
                    CASE
                        WHEN question LIKE '%2+2%' THEN 0
                        WHEN question LIKE '%4+0%' THEN 1
                        WHEN question LIKE '%必须去英国%' THEN 2
                        WHEN question LIKE '%不去英国%' THEN 3
                        ELSE 4
                    END,
                    id
                LIMIT 5
                """
            ).fetchall()
        conn.close()

        if not rows:
            return ""

        lines = []
        for idx, row in enumerate(rows, 1):
            lines.append(
                f"[FAQ-{idx}] 问题：{row['question']}\n"
                f"分类：{row['category']}\n"
                f"来源：{row['source_url']}\n"
                f"答案：{row['answer']}"
            )
        return "\n\n".join(lines)
    except Exception:
        return ""


def _build_school_overview_context(message: str, source_db: str) -> tuple[str, list[dict[str, str]]]:
    """Return the canonical school overview for broad XJTLU introduction queries."""
    overview_terms = ["介绍", "简介", "概况", "是什么学校", "什么大学", "了解一下", "讲讲", "说说"]
    school_terms = ["西交利物浦大学", "西交利物浦", "西浦", "xjtlu"]
    lowered = message.lower()
    if not any(term in lowered for term in school_terms):
        return "", []
    if not any(term in message for term in overview_terms):
        return "", []

    try:
        conn = sqlite3.connect(source_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT title, content, category, source_url
            FROM school_info
            WHERE title LIKE '%学校概况%'
               OR category LIKE '%学校简介%'
               OR content LIKE '%合作创立%'
            ORDER BY
                CASE
                    WHEN title LIKE '%学校概况%' THEN 0
                    WHEN category LIKE '%学校简介%' THEN 1
                    ELSE 2
                END,
                id
            LIMIT 1
            """
        ).fetchone()
        conn.close()
    except Exception:
        return "", []

    if not row:
        return "", []

    context = (
        f"[学校概况] 标题：{row['title']}\n"
        f"分类：{row['category']}\n"
        f"来源：{row['source_url']}\n"
        f"内容：{row['content']}"
    )
    source = {
        "title": row["title"],
        "url": row["source_url"],
        "category": row["category"],
        "score": 1.0,
    }
    return context, [source]


IDENTITY_MAP = {
    "招生顾问": "你是西交利物浦大学中文招生顾问，回答要清晰、谨慎、面向学生和家长。",
    "学术导师": "你是西交利物浦大学学术导师，回答要重视专业选择、课程路径和学术发展。",
    "校园助手": "你是西交利物浦大学校园助手，回答要自然、友好、简洁。",
}


def _infer_identity(message: str, current: str) -> str:
    for identity in IDENTITY_MAP:
        if identity in message:
            return identity
    if "招生" in message and ("身份" in message or "你是" in message or "作为" in message):
        return "招生顾问"
    if "导师" in message and ("身份" in message or "你是" in message or "作为" in message):
        return "学术导师"
    return current or "校园助手"


def _extract_profile_updates(message: str) -> dict[str, str]:
    updates: dict[str, str] = {}
    patterns = {
        "name": r"(?:我叫|我的名字是|我是)([\u4e00-\u9fa5A-Za-z0-9_\-]{1,20})",
        "major_interest": r"(?:我想了解|我对|我感兴趣的是|我感兴趣)([^。；;,.，]{2,40})",
        "language": r"(?:以后用|请用)(中文|英文|中英双语|英文为主|中文为主)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, message)
        if match:
            updates[key] = match.group(1).strip()
    return updates


def _needs_rag(message: str) -> bool:
    casual_patterns = ["你好", "hi", "hello", "谢谢", "你是谁", "早上好", "晚上好", "再见"]
    if len(message.strip()) <= 8 and any(word in message.lower() for word in casual_patterns):
        return False
    school_keywords = [
        "西浦",
        "西交利物浦",
        "xjtlu",
        "专业",
        "课程",
        "学费",
        "学院",
        "申请",
        "招生",
        "录取",
        "校园",
        "苏州",
        "利物浦",
        "大学",
        "本科",
        "硕士",
        "博士",
    ]
    return any(word in message.lower() for word in school_keywords)


def _format_context(results: list[SearchResult]) -> str:
    lines = []
    for idx, item in enumerate(results, 1):
        content = item.content[:1200]
        lines.append(
            f"[{idx}] 标题：{item.title}\n分类：{item.category}\n相似度：{item.score:.3f}\n来源：{item.url}\n内容：{content}"
        )
    return "\n\n".join(lines)


def _format_history(messages: list[dict[str, str]]) -> str:
    return "\n".join(f"{item['role']}: {item['content']}" for item in messages)


async def chat(session_id: str, message: str) -> dict:
    profile = get_profile(settings.memory_db, session_id)
    identity = _infer_identity(message, profile.get("assistant_identity", "校园助手"))
    updates = _extract_profile_updates(message)
    updates["assistant_identity"] = identity
    upsert_profile(settings.memory_db, session_id, updates)
    profile = get_profile(settings.memory_db, session_id)

    add_message(settings.memory_db, session_id, "user", message)
    history = recent_messages(settings.memory_db, session_id, limit=8)

    results: list[SearchResult] = []
    rag_embed_sec = 0.0
    rag_search_sec = 0.0
    if _needs_rag(message):
        t0 = time.monotonic()
        query_embedding = await embed_text(message)
        rag_embed_sec = round(time.monotonic() - t0, 3)
        t1 = time.monotonic()
        results = search(settings.rag_db, query_embedding, settings.top_k, settings.similarity_threshold)
        rag_search_sec = round(time.monotonic() - t1, 3)

    direct_faq_context = _build_direct_faq_context(message, settings.source_db)
    programme_context = _build_programme_context(message, settings.source_db)
    school_overview_context, direct_sources = _build_school_overview_context(message, settings.source_db)

    system = f"""
{IDENTITY_MAP.get(identity, IDENTITY_MAP["校园助手"])}

你需要同时具备三种能力：
1. 记住用户明确提供的身份属性，例如姓名、关注专业、语言偏好、对助手身份的要求。
2. 能自然闲聊；闲聊问题不强行引用知识库。
3. 涉及西交利物浦大学/XJTLU/专业/招生/学院/校园事实时，优先依据知识库上下文回答。
   当知识库提供了"学校概况补充"、"FAQ精准补充"或"专业数据库补充"内容时，必须以该内容为基础进行回答，不要说"知识库没有足够信息"。

回答规则：
- 使用中文，除非用户要求其他语言。
- answer 必须控制在100个中文字符以内，直接回答核心结论，不展开长列表。
- 不要在 answer 里列“参考来源”；来源会由系统通过 sources 字段单独返回。
- 知识库不足以确认时，明确说“当前知识库没有足够依据”，再给出可核实的建议。
- 不要编造学费、截止日期、录取要求等高风险信息。
- 用户画像只用于改善回答，不要暴露内部推断过程。
- 同时判断这次机器人回复最适合搭配哪个手臂动作。动作只能从动作白名单中选择。
- 如果回复只是信息说明、查询结果、普通陈述、无法用动作表达、或不适合动，选择“无动作”。
- 如果用户或回复表达攻击、威胁、伤害、挑衅、打人、消灭、攻击目标等舞台化表达，选择“x-ray”。这里的“x-ray”只是非接触表演动作。
- 只输出严格 JSON，不要 Markdown，不要额外文字。
""".strip()

    prompt = f"""
用户画像：
{json.dumps(profile, ensure_ascii=False)}

最近对话：
{_format_history(history)}

知识库上下文：
{_format_context(results) if results else "无"}
{f"\n\n【学校概况补充】\n{school_overview_context}" if school_overview_context else ""}
{f"\n\n【FAQ精准补充】\n{direct_faq_context}" if direct_faq_context else ""}
{f"\n\n【专业数据库补充】\n{programme_context}" if programme_context else ""}

用户当前问题：
{message}

动作白名单：
{json.dumps([asdict(action) for action in ACTIONS], ensure_ascii=False)}

输出 JSON schema：
{{
  "answer": "100字以内最终回复",
  "action": {{
    "label": "必须是动作白名单中的 label",
    "confidence": 0到1之间的数字,
    "reason": "一句简短中文理由"
  }}
}}
""".strip()

    t2 = time.monotonic()
    model_payload = _parse_json_object(await generate_text(prompt, system))
    answer = _limit_answer(str(model_payload.get("answer", "")).strip())
    action = _normalize_action(model_payload.get("action"))
    llm_sec = round(time.monotonic() - t2, 3)
    add_message(settings.memory_db, session_id, "assistant", answer)

    return {
        "answer": answer,
        "action": action,
        "identity": identity,
        "profile": profile,
        "sources": direct_sources + [
            {
                "title": item.title,
                "url": item.url,
                "category": item.category,
                "score": round(item.score, 4),
            }
            for item in results
        ],
        "timing": {
            "rag_embed_sec": rag_embed_sec,
            "rag_search_sec": rag_search_sec,
            "llm_sec": llm_sec,
            "total_sec": round(rag_embed_sec + rag_search_sec + llm_sec, 3),
        },
    }
