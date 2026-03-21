from __future__ import annotations

import asyncio

from agents.pipeline.state import PipelineState, append_message
from agents.pipeline.nodes.utils import deduplicate_keywords, extract_keywords_from_text, parse_json_object
from core.llm_client import chat, is_configured
from services.pipeline_runtime_service import get_pipeline_runtime_service

_NODE = "planner"


def _fallback_plan(state: PipelineState) -> tuple[str, list[str], list[str]]:
    input_value = str(state.get("input_value") or "").strip()
    input_type = str(state.get("input_type") or "domain").strip()
    research_goal = f"围绕“{input_value}”完成结构化调研并输出可执行结论。"

    if input_type in {"arxiv_id", "doi"}:
        execution_plan = [
            "定位核心论文与直接关联论文",
            "构建知识图谱并识别主要研究分支",
            "并行生成血缘脉络与研究空白",
            "汇总空白点并给出研究建议",
        ]
    else:
        execution_plan = [
            "解析研究方向并扩展检索关键词",
            "检索并筛选代表性论文",
            "构建知识图谱识别子方向",
            "并行分析血缘脉络与研究空白",
            "输出结构化研究结论",
        ]

    keywords = deduplicate_keywords(extract_keywords_from_text(input_value, limit=6) or [input_value])
    return research_goal, execution_plan, keywords


async def _plan_with_llm(state: PipelineState) -> tuple[str, list[str], list[str]]:
    input_desc = f"{state['input_type']}: {state['input_value']}"
    system_prompt = (
        "你是科研工作流规划助手。"
        "请输出严格 JSON："
        "{\"research_goal\":string,\"execution_plan\":string[],\"search_keywords\":string[]}。"
        "execution_plan 输出 3-6 步，search_keywords 输出 3-8 个关键词。"
    )
    user_prompt = f"用户输入：{input_desc}"

    response = await asyncio.wait_for(
        asyncio.to_thread(
            chat,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            timeout=20,
        ),
        timeout=22,
    )
    content = ""
    try:
        content = str(response.choices[0].message.content or "").strip()
    except Exception:  # noqa: BLE001
        content = ""

    parsed = parse_json_object(content)
    research_goal = str(parsed.get("research_goal") or "").strip()
    execution_plan = [
        str(item).strip()
        for item in (parsed.get("execution_plan") or [])
        if str(item).strip()
    ]
    keywords = deduplicate_keywords([
        str(item).strip()
        for item in (parsed.get("search_keywords") or [])
        if str(item).strip()
    ])

    fallback_goal, fallback_plan, fallback_keywords = _fallback_plan(state)
    return (
        research_goal or fallback_goal,
        execution_plan or fallback_plan,
        keywords or fallback_keywords,
    )


async def planner_node(state: PipelineState) -> PipelineState:
    runtime = get_pipeline_runtime_service()
    session_id = state["session_id"]

    await runtime.ensure_active(session_id)
    await runtime.emit_node_start(session_id, _NODE, 5)

    if is_configured():
        try:
            research_goal, execution_plan, keywords = await _plan_with_llm(state)
        except Exception:  # noqa: BLE001
            research_goal, execution_plan, keywords = _fallback_plan(state)
    else:
        research_goal, execution_plan, keywords = _fallback_plan(state)

    await runtime.emit_thinking(session_id, _NODE, f"研究目标：{research_goal}")

    summary = f"已完成研究规划，生成 {len(execution_plan)} 个执行步骤与 {len(keywords)} 个关键词。"
    await runtime.emit_node_complete(session_id, _NODE, 10, summary)

    return {
        **state,
        "research_goal": research_goal,
        "execution_plan": execution_plan,
        "search_keywords": keywords,
        "current_node": _NODE,
        "progress": 10,
        "messages": append_message(state, summary),
    }
