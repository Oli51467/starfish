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
            "请作为科研多智能体中的一个子角色，基于上下文输出一段中文洞察。"
            "内容必须包含：当前发展判断、证据指向、可行创新方向。"
            "上下文："
            f"{context}"
        )
    return (
        "Act as a sub-agent in a research multi-agent system and provide one concise insight paragraph in English. "
        "Must include: current status judgment, evidence cue, feasible innovation direction. "
        f"Context: {context}"
    )


def _fallback_output(payload: dict[str, Any]) -> str:
    role = payload.get("role") if isinstance(payload.get("role"), dict) else {}
    language = str(payload.get("language") or "en")
    round_index = _safe_int(payload.get("round_index"), 1)
    query = str(payload.get("query") or "").strip()
    papers = list(payload.get("papers") or [])
    extension_papers = list(payload.get("extension_papers") or [])
    graph_stats = payload.get("graph_stats") if isinstance(payload.get("graph_stats"), dict) else {}
    node_count = _safe_int(graph_stats.get("node_count"), 0)
    edge_count = _safe_int(graph_stats.get("edge_count"), 0)
    total_papers = len(papers) + len(extension_papers)

    if language == "zh":
        return (
            f"[R{round_index}] {str(role.get('title_zh') or '子代理')}：围绕“{query}”，"
            f"当前证据池共 {total_papers} 篇论文，图谱节点 {node_count}、关系 {edge_count}。"
            f"建议聚焦“{str(role.get('focus') or '')}”并设计可验证的增量实验。"
        )
    return (
        f"[R{round_index}] {str(role.get('title_en') or 'Sub-agent')}: For '{query}', "
        f"the evidence pool has {total_papers} papers with {node_count} graph nodes and {edge_count} relations. "
        f"Prioritize '{str(role.get('focus') or '')}' with a verifiable incremental experiment path."
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
                            "You are a specialized research sub-agent. "
                            "Return one concise paragraph with actionable insights."
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
