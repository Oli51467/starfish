from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from typing import Any

# Ensure sibling backend modules are importable when this file is executed directly.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from core.llm_client import chat, is_configured


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(math.floor(float(value)))
    except (TypeError, ValueError):
        return default


def _top_papers_for_prompt(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    sorted_items = sorted(
        [dict(item) for item in items if isinstance(item, dict)],
        key=lambda item: (
            _safe_int(item.get("citation_count"), 0),
            _safe_int(item.get("year"), 0),
        ),
        reverse=True,
    )
    return sorted_items[: max(1, limit)]


def _build_role_prompt(payload: dict[str, Any]) -> str:
    language = str(payload.get("language") or "en")
    role = payload.get("role") if isinstance(payload.get("role"), dict) else {}
    role_name = str(role.get("title_zh") or "") if language == "zh" else str(role.get("title_en") or "")
    papers = list(payload.get("papers") or [])
    extension_papers = list(payload.get("extension_papers") or [])
    history_memory = [str(item) for item in (payload.get("history_memory") or []) if str(item).strip()]
    session_memory = payload.get("session_memory") if isinstance(payload.get("session_memory"), dict) else {}

    context = {
        "query": str(payload.get("query") or ""),
        "round": _safe_int(payload.get("round_index"), 1),
        "role": role_name,
        "focus": str(role.get("focus") or ""),
        "objective": str(payload.get("objective") or "").strip(),
        "graph_stats": payload.get("graph_stats") if isinstance(payload.get("graph_stats"), dict) else {},
        "top_papers": _top_papers_for_prompt(papers + extension_papers, limit=6),
        "history_memory": history_memory[:2],
        "session_hypotheses": (session_memory.get("hypotheses") or [])[-2:],
        "session_critic_notes": (session_memory.get("critic_notes") or [])[-2:],
    }
    if language == "zh":
        return (
            "你是科研分析写作助手。请基于上下文输出一段中文深度分析（220-420字）。"
            "内容必须包含：证据链（引用论文标题/年份）、关键判断、可执行建议。"
            "禁止描述工作流、Agent、子代理、协商轮次、工具调用过程。"
            "上下文："
            f"{context}"
        )
    return (
        "You are a research writing analyst. Produce one deep English paragraph (150-260 words). "
        "The paragraph must include evidence links (paper title/year), key judgments, and executable recommendations. "
        "Do not describe workflow, agents, rounds, or tool invocation process. "
        f"Context: {context}"
    )


def _fallback_output(payload: dict[str, Any]) -> str:
    language = str(payload.get("language") or "en")
    query = str(payload.get("query") or "").strip()
    papers = list(payload.get("papers") or [])
    extension_papers = list(payload.get("extension_papers") or [])
    graph_stats = payload.get("graph_stats") if isinstance(payload.get("graph_stats"), dict) else {}
    node_count = _safe_int(graph_stats.get("node_count"), 0)
    edge_count = _safe_int(graph_stats.get("edge_count"), 0)
    total_papers = len(papers) + len(extension_papers)

    if language == "zh":
        return (
            f"围绕“{query}”的证据样本当前包含 {total_papers} 篇论文，图谱节点 {node_count}、关系 {edge_count}。"
            "建议围绕“鼻祖论文起源、延续工作细节、当前落地场景、创新空白”形成连续证据链并给出可验证建议。"
        )
    return (
        f"For '{query}', the current evidence sample contains {total_papers} papers "
        f"with {node_count} graph nodes and {edge_count} relations. "
        "Build a continuous evidence-backed storyline from seminal origin to continuation works, deployment, and innovation gaps."
    )


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    allow_llm = bool(payload.get("allow_llm"))
    if allow_llm and is_configured():
        prompt = _build_role_prompt(payload)
        try:
            response = chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a specialized research analyst. "
                            "Return one deep paragraph with evidence-backed and actionable insights."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25,
                timeout=20,
            )
            content = str(response.choices[0].message.content or "").strip()
            if content:
                return {
                    "status": "completed",
                    "output": content,
                }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "fallback",
                "output": _fallback_output(payload),
                "error": str(exc),
            }

    return {
        "status": "fallback",
        "output": _fallback_output(payload),
    }


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
    result = execute(payload if isinstance(payload, dict) else {})
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
