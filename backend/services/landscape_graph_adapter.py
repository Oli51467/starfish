from __future__ import annotations

import re
from typing import Any


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    return value or "node"


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _domain_relevance(direction: dict[str, Any]) -> float:
    correlation = direction.get("correlation_score")
    if correlation is not None:
        try:
            return max(0.08, min(float(correlation), 1.0))
        except (TypeError, ValueError):
            pass
    recent_ratio = max(0.0, min(_safe_float(direction.get("recent_ratio")), 1.0))
    avg_citations = _safe_float(direction.get("avg_citations"))
    paper_count = _safe_float(direction.get("paper_count"))
    return max(
        0.08,
        min(
            recent_ratio * 0.5
            + min(avg_citations / 600.0, 1.0) * 0.3
            + min(paper_count / 40.0, 1.0) * 0.2,
            1.0,
        ),
    )


def _paper_relevance(paper: dict[str, Any]) -> float:
    citation = _safe_float(paper.get("citation_count"))
    year = _safe_int(paper.get("year"))
    citation_score = min(citation / 2000.0, 1.0)
    recency_boost = 0.15 if year >= 2023 else 0.0
    return max(0.12, min(0.22 + citation_score * 0.72 + recency_boost, 1.0))


def build_landscape_graph(
    landscape: dict[str, Any],
    *,
    max_papers_per_direction: int = 15,
) -> dict[str, Any]:
    domain_name = str(landscape.get("domain_name") or landscape.get("query") or "领域").strip()
    seed_id = f"seed:{_slug(domain_name)}"

    nodes: dict[str, dict[str, Any]] = {
        seed_id: {
            "id": seed_id,
            "name": domain_name,
            "label": domain_name,
            "kind": "seed",
            "relevance": 1.0,
            "score": 1.0,
            "meta": {
                "query": domain_name,
                "abstract": f"{domain_name} 领域知识图谱（实时生成）",
            },
        }
    }
    edges: list[dict[str, Any]] = []
    paper_node_count = 0

    sub_directions = list(landscape.get("sub_directions") or [])
    for index, direction in enumerate(sub_directions):
        direction_name = str(direction.get("name") or "").strip()
        if not direction_name:
            continue

        direction_id = f"domain:{index}:{_slug(direction_name)}"
        relevance = _domain_relevance(direction)
        methods = [str(item).strip() for item in (direction.get("methods") or []) if str(item).strip()]
        related_papers: list[dict[str, Any]] = []
        for paper in (direction.get("core_papers") or [])[: max(0, max_papers_per_direction)]:
            if not isinstance(paper, dict):
                continue
            related_papers.append(
                {
                    "id": str(paper.get("id") or "").strip(),
                    "title": str(paper.get("title") or "").strip(),
                    "year": _safe_int(paper.get("year")),
                    "citation_count": _safe_int(paper.get("citation_count")),
                    "authors": ", ".join(
                        str(item).strip()
                        for item in (paper.get("authors") or [])
                        if str(item).strip()
                    ),
                }
            )

        nodes[direction_id] = {
            "id": direction_id,
            "name": direction_name,
            "label": direction_name,
            "kind": "domain",
            "relevance": relevance,
            "score": relevance,
            "meta": {
                "paper_count": str(_safe_int(direction.get("paper_count"))),
                "recent_ratio": str(round(max(0.0, min(_safe_float(direction.get("recent_ratio")), 1.0)), 3)),
                "avg_citations": str(_safe_int(direction.get("avg_citations"))),
                "status": str(direction.get("status") or "stable"),
                "provider_used": str(direction.get("provider_used") or ""),
                "description": str(direction.get("description") or ""),
                "methods": "|".join(methods),
                "related_papers": related_papers,
            },
        }
        edges.append(
            {
                "id": f"{seed_id}->{direction_id}",
                "source": seed_id,
                "target": direction_id,
                "kind": "center",
                "relevance": relevance,
                "weight": relevance,
            }
        )

        for paper_index, paper in enumerate(related_papers):
            paper_title = str(paper.get("title") or "").strip()
            if not paper_title:
                continue
            raw_paper_id = str(paper.get("id") or "").strip() or f"{direction_id}:paper:{paper_index}:{_slug(paper_title)}"
            paper_id = f"paper:{raw_paper_id}"
            paper_relevance = _paper_relevance(paper)
            if paper_id not in nodes:
                nodes[paper_id] = {
                    "id": paper_id,
                    "name": paper_title,
                    "label": paper_title,
                    "kind": "paper",
                    "relevance": paper_relevance,
                    "score": paper_relevance,
                    "meta": {
                        "title": paper_title,
                        "year": str(_safe_int(paper.get("year"))),
                        "published_month": "1",
                        "venue": "Unknown Venue",
                        "authors": str(paper.get("authors") or "").strip(),
                        "abstract": f"{direction_name} 的代表论文",
                        "citation_count": str(_safe_int(paper.get("citation_count"))),
                        "relevance": f"{paper_relevance:.3f}",
                        "keywords": str(direction.get("description") or ""),
                    },
                }
                paper_node_count += 1

            edges.append(
                {
                    "id": f"{direction_id}->{paper_id}",
                    "source": direction_id,
                    "target": paper_id,
                    "kind": "related",
                    "relevance": max(0.18, relevance * 0.82),
                    "weight": max(0.18, relevance * 0.82),
                }
            )

    domain_count = sum(1 for node in nodes.values() if node.get("kind") == "domain")
    return {
        "title": f"{domain_name} 领域图谱",
        "nodes": list(nodes.values()),
        "edges": edges,
        "counts": {
            "seed": 1,
            "domain": domain_count,
            "paper": paper_node_count,
            "edges": len(edges),
        },
    }
