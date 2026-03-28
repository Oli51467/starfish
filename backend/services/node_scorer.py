from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
from typing import Any


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, parsed)


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _paper_key(value: Any) -> str:
    return str(value or "").strip().lower()


def compute_internal_citations_from_papers(papers: list[dict[str, Any]]) -> dict[str, int]:
    """Count inbound citation links between papers included in the same graph."""
    id_by_key: dict[str, str] = {}
    for paper in papers:
        paper_id = str(paper.get("paper_id") or "").strip()
        key = _paper_key(paper_id)
        if paper_id and key:
            id_by_key[key] = paper_id

    inbound: Counter[str] = Counter()
    for paper in papers:
        source_id = str(paper.get("paper_id") or "").strip()
        source_key = _paper_key(source_id)
        if not source_id or not source_key:
            continue

        seen_targets: set[str] = set()
        for reference_id in (paper.get("reference_ids") or []):
            target_id = id_by_key.get(_paper_key(reference_id))
            if not target_id or target_id == source_id or target_id in seen_targets:
                continue
            seen_targets.add(target_id)
            inbound[target_id] += 1

        seen_citers: set[str] = set()
        for citer_id in (paper.get("citation_ids") or []):
            mapped_citer_id = id_by_key.get(_paper_key(citer_id))
            if not mapped_citer_id or mapped_citer_id == source_id or mapped_citer_id in seen_citers:
                continue
            seen_citers.add(mapped_citer_id)
            inbound[source_id] += 1

    return {
        paper_id: int(inbound.get(paper_id, 0))
        for paper_id in id_by_key.values()
    }


def compute_internal_citations_from_edges(
    node_ids: list[str],
    edges: list[dict[str, Any]],
) -> dict[str, int]:
    """Count inbound links by edge target for a given node id set."""
    allowed = {str(node_id or "").strip() for node_id in node_ids if str(node_id or "").strip()}
    inbound: Counter[str] = Counter()
    for edge in edges:
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target or source == target:
            continue
        if source not in allowed or target not in allowed:
            continue
        inbound[target] += 1

    return {
        node_id: int(inbound.get(node_id, 0))
        for node_id in allowed
    }


def score_paper_nodes(
    papers: list[dict[str, Any]],
    *,
    max_tier1: int = 3,
) -> list[dict[str, Any]]:
    """Add importance/tier/rendering fields to paper records."""
    if not papers:
        return []

    current_year = datetime.now().year
    max_citations = max((_safe_int(paper.get("citation_count")) for paper in papers), default=1)
    max_internal = max((_safe_int(paper.get("internal_citations")) for paper in papers), default=1)
    max_citations = max(1, max_citations)
    max_internal = max(1, max_internal)

    enriched: list[dict[str, Any]] = []
    for paper in papers:
        citation_count = _safe_int(paper.get("citation_count"))
        internal_citations = _safe_int(paper.get("internal_citations"))
        raw_year = _safe_int(paper.get("year"), fallback=current_year)
        year = raw_year if raw_year > 0 else current_year

        query_relevance = _clamp(
            _safe_float(
                paper.get("query_relevance", paper.get("relevance", paper.get("semantic_score", 0.0))),
                0.0,
            ),
            0.0,
            1.0,
        )

        citation_score = math.log1p(citation_count) / math.log1p(max_citations) * 30.0
        internal_score = (internal_citations / max_internal) * 22.0
        relevance_score = query_relevance * 33.0

        age = max(0, current_year - year)
        if age >= 6 and citation_count >= max(80, int(max_citations * 0.12)):
            time_score = 12.0
        elif age <= 2 and citation_count >= max(30, int(max_citations * 0.03)):
            time_score = 10.0
        elif age <= 2:
            time_score = 7.0
        else:
            time_score = max(2.0, 11.0 - age * 0.65)

        importance_score = _clamp(citation_score + internal_score + relevance_score + time_score, 0.0, 100.0)
        enriched.append(
            {
                **paper,
                "year": year,
                "query_relevance": query_relevance,
                "importance_score": round(importance_score, 3),
            }
        )

    ranked = sorted(enriched, key=lambda item: item.get("importance_score", 0.0), reverse=True)
    total = max(1, len(ranked))

    for index, paper in enumerate(ranked):
        score = _safe_float(paper.get("importance_score"))
        rank_ratio = index / total
        if score >= 74 or (rank_ratio < 0.10 and score >= 58):
            tier = 1
        elif score >= 45 or rank_ratio < 0.36:
            tier = 2
        else:
            tier = 3
        paper["tier"] = tier

    tier1 = [paper for paper in ranked if int(paper.get("tier", 3)) == 1]
    if len(tier1) > max_tier1:
        for paper in tier1[max_tier1:]:
            paper["tier"] = 2

    tier_base = {1: 46.0, 2: 32.0, 3: 20.0}
    for paper in ranked:
        tier = int(paper.get("tier") or 3)
        relevance = _clamp(_safe_float(paper.get("query_relevance")), 0.0, 1.0)
        importance = _clamp(_safe_float(paper.get("importance_score")), 0.0, 100.0)
        base = tier_base.get(tier, 20.0)
        score_bonus = (importance / 100.0) * 8.0
        relevance_bonus = relevance * 4.0

        node_size = _clamp(base + score_bonus + relevance_bonus, 16.0, 64.0)
        color_weight = _clamp(0.2 + (importance / 100.0) * 0.8, 0.2, 1.0)

        paper["node_size"] = round(node_size, 3)
        paper["node_color_weight"] = round(color_weight, 3)

    score_by_id = {
        str(item.get("id") or ""): item
        for item in ranked
    }
    result: list[dict[str, Any]] = []
    for paper in papers:
        paper_id = str(paper.get("id") or "")
        merged = score_by_id.get(paper_id)
        if merged:
            result.append(merged)
        else:
            result.append(
                {
                    **paper,
                    "importance_score": 0.0,
                    "tier": 3,
                    "node_size": 20.0,
                    "node_color_weight": 0.2,
                }
            )
    return result


def build_aha_summary(query: str, papers: list[dict[str, Any]]) -> str:
    if not papers:
        topic = str(query or "该方向").strip() or "该方向"
        return f"正在分析 {topic} 的核心论文脉络。"

    ranked = sorted(
        papers,
        key=lambda item: (
            int(item.get("tier") or 3),
            -_safe_float(item.get("importance_score")),
        ),
    )
    head = ranked[0]
    head_title = str(head.get("title") or "未命名论文").strip() or "未命名论文"
    head_year = _safe_int(head.get("year"))

    tier2_count = sum(1 for item in papers if int(item.get("tier") or 3) == 2)

    core_text = f"该领域当前的核心论文是《{head_title}》"
    if head_year > 0:
        core_text = f"{core_text}（{head_year}）"

    return f"{core_text}，并延展出 {tier2_count} 个关键分支。"
