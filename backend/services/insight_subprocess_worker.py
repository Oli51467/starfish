from __future__ import annotations

import json
import math
from pathlib import Path
import re
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


def _summarize_abstract_text(text: object, *, max_chars: int) -> str:
    safe = str(text or "").strip()
    if not safe:
        return ""
    safe = re.sub(r"\s+", " ", safe)
    limit = max(40, int(max_chars))
    if len(safe) <= limit:
        return safe
    return f"{safe[: max(1, limit - 3)].rstrip()}..."


def _extract_query_terms(query: str) -> list[str]:
    safe_query = re.sub(r"\s+", " ", str(query or "").strip().lower())
    if not safe_query:
        return []
    english_terms = re.findall(r"[a-z0-9][a-z0-9\-]{2,}", safe_query)
    cjk_terms = [item for item in re.findall(r"[\u4e00-\u9fff]{2,}", safe_query) if len(item) >= 2]
    terms: list[str] = []
    seen: set[str] = set()
    for token in [safe_query, *english_terms, *cjk_terms]:
        normalized = str(token or "").strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
        if len(terms) >= 12:
            break
    return terms


def _rank_papers_by_query_relevance(
    papers: list[dict[str, Any]],
    *,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    terms = _extract_query_terms(query)
    if not terms:
        return _top_papers_for_prompt(papers, limit=max(1, int(limit)))
    full_phrase = terms[0]
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in papers:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        abstract = str(item.get("abstract") or "").strip()
        if not title and not abstract:
            continue
        title_lc = title.lower()
        abstract_lc = abstract.lower()
        score = 0.0
        if full_phrase and full_phrase in title_lc:
            score += 10.0
        elif full_phrase and full_phrase in abstract_lc:
            score += 6.0
        for token in terms[1:]:
            if token in title_lc:
                score += 3.6
            elif token in abstract_lc:
                score += 1.8
        citations = _safe_int(item.get("citation_count"), 0)
        year = _safe_int(item.get("year"), 0)
        score += min(8.0, float(max(0, citations)) / 900.0)
        if year >= 2020:
            score += 1.2
        elif year >= 2016:
            score += 0.7
        scored.append((score, dict(item)))
    scored.sort(
        key=lambda pair: (
            pair[0],
            _safe_int(pair[1].get("citation_count"), 0),
            _safe_int(pair[1].get("year"), 0),
        ),
        reverse=True,
    )
    return [item for _, item in scored[: max(1, int(limit))]]


def _build_role_prompt(payload: dict[str, Any]) -> str:
    language = str(payload.get("language") or "en")
    role = payload.get("role") if isinstance(payload.get("role"), dict) else {}
    role_name = str(role.get("title_zh") or "") if language == "zh" else str(role.get("title_en") or "")
    papers = list(payload.get("papers") or [])
    extension_papers = list(payload.get("extension_papers") or [])
    history_memory = [str(item) for item in (payload.get("history_memory") or []) if str(item).strip()]
    session_memory = payload.get("session_memory") if isinstance(payload.get("session_memory"), dict) else {}

    ranked = _rank_papers_by_query_relevance(
        papers + extension_papers,
        query=str(payload.get("query") or ""),
        limit=6,
    )
    evidence_cards = [
        {
            "id": f"E{index}",
            "title": str(item.get("title") or "Unknown title").strip() or "Unknown title",
            "year": _safe_int(item.get("year"), 0),
            "venue": str(item.get("venue") or "Unknown").strip() or "Unknown",
            "citations": _safe_int(item.get("citation_count"), 0),
            "abstract_hint": _summarize_abstract_text(item.get("abstract"), max_chars=180),
        }
        for index, item in enumerate(ranked, start=1)
    ]
    context = {
        "query": str(payload.get("query") or ""),
        "round": _safe_int(payload.get("round_index"), 1),
        "role": role_name,
        "focus": str(role.get("focus") or ""),
        "objective": str(payload.get("objective") or "").strip(),
        "graph_stats": payload.get("graph_stats") if isinstance(payload.get("graph_stats"), dict) else {},
        "evidence_cards": evidence_cards,
        "history_memory": history_memory[:2],
        "session_hypotheses": (session_memory.get("hypotheses") or [])[-2:],
        "session_critic_notes": (session_memory.get("critic_notes") or [])[-2:],
    }
    if language == "zh":
        return (
            "你是科研分析写作助手，请输出严谨、可核验、可执行的中文分析。"
            "严禁描述工作流、智能体、子代理、协同轮次与工具调用。"
            "必须使用证据编号(E1/E2...)，且至少引用2条证据。"
            "输出必须严格为四行："
            "核心判断：..."
            "证据条目：...（示例：[E1] 论文名(年份)）"
            "可执行建议：..."
            "不确定性：..."
            f"上下文：{context}"
        )
    return (
        "You are a scientific writing analyst. "
        "Never describe workflow, agents, orchestration rounds, or tool calls. "
        "Use at least two evidence markers (E1/E2...) from provided evidence only. "
        "Output must be exactly four lines with these prefixes: "
        "Core Judgment: ... "
        "Evidence: ... (example: [E1] Paper Title (Year)) "
        "Actionable Recommendation: ... "
        "Uncertainty: ... "
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

    ranked = _rank_papers_by_query_relevance(
        papers + extension_papers,
        query=query,
        limit=1,
    )
    top_item = ranked[0] if ranked else None
    if isinstance(top_item, dict):
        title = str(top_item.get("title") or "Unknown title").strip() or "Unknown title"
        year = _safe_int(top_item.get("year"), 0)
        evidence = f"{title} ({year or 'year unknown'})"
    else:
        evidence = ""

    if language == "zh":
        return "\n".join(
            [
                f"核心判断：围绕“{query}”已形成可分析证据主线，但仍需进一步收敛关键机制结论。",
                f"证据条目：{('[E1] ' + evidence) if evidence else '当前样本未提供高置信证据条目。'}",
                "可执行建议：先构建最小证据链并进行可量化评测（质量/时延/成本）。",
                (
                    f"不确定性：当前样本 {total_papers} 篇（节点 {node_count}、关系 {edge_count}），"
                    "结论的跨场景泛化仍需验证。"
                ),
            ]
        )
    return "\n".join(
        [
            f"Core Judgment: For '{query}', the evidence line is analyzable but still insufficient for strong mechanism claims.",
            f"Evidence: {('[E1] ' + evidence) if evidence else 'No high-confidence evidence item is available in the current sample.'}",
            "Actionable Recommendation: Build a minimal evidence chain and validate with measurable metrics (quality/latency/cost).",
            (
                f"Uncertainty: Current sample size is {total_papers} papers ({node_count} nodes, {edge_count} relations), "
                "so cross-domain generalization remains uncertain."
            ),
        ]
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
                            "You are a senior scientific analyst. "
                            "Write rigorous, evidence-grounded content only. "
                            "Do not mention workflows, agents, orchestration, rounds, or tool calls."
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
