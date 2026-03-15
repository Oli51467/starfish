from __future__ import annotations

from functools import lru_cache
import json
import logging
from typing import Any

from models.schemas import (
    KnowledgeGraphBuildRequest,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeGraphResponse,
    LandscapeGenerateRequest,
    LandscapeResponse,
    ResearchHistoryDetailResponse,
    ResearchHistoryLineageStatus,
    ResearchHistoryListItem,
    ResearchHistoryListResponse,
    UserProfile,
)
from repositories.research_history_repository import (
    ResearchHistoryRepository,
    get_research_history_repository,
)

logger = logging.getLogger(__name__)

_VALID_RESEARCH_TYPES = {"arxiv_id", "doi", "domain"}


class ResearchHistoryService:
    def __init__(self, repository: ResearchHistoryRepository | None = None) -> None:
        self.repository = repository or get_research_history_repository()

    def record_graph_result(
        self,
        *,
        user: UserProfile,
        request: KnowledgeGraphBuildRequest,
        graph: KnowledgeGraphResponse,
    ) -> str | None:
        research_type = self._normalize_research_type(request.research_type)
        search_record = str(request.search_input or "").strip() or str(request.query or "").strip()
        if not search_record:
            search_record = "unknown"

        try:
            return self.repository.save_graph_record(
                user_id=user.id,
                user_email=user.email,
                research_type=research_type,
                search_record=search_record,
                search_range=self._normalize_search_range(
                    request.search_range,
                    research_type=research_type,
                ),
                graph_id=graph.graph_id,
                graph_payload=graph.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed persisting research history record.")
            return None

    def record_landscape_result(
        self,
        *,
        user: UserProfile,
        request: LandscapeGenerateRequest,
        landscape: LandscapeResponse,
    ) -> str | None:
        try:
            graph = self._to_history_graph(landscape)
            raw_landscape_graph = landscape.graph_data if isinstance(landscape.graph_data, dict) else {}
            return self.repository.save_graph_record(
                user_id=user.id,
                user_email=user.email,
                research_type="domain",
                search_record=str(request.query or "").strip() or str(landscape.query or "").strip() or "unknown",
                search_range=self._normalize_search_range(
                    self._format_domain_search_range(request.paper_range_years),
                    research_type="domain",
                ),
                graph_id=graph.graph_id,
                graph_payload={
                    "graph": graph.model_dump(mode="json"),
                    "landscape_graph": raw_landscape_graph,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed persisting landscape history record.")
            return None

    def list_history(self, *, user: UserProfile, page: int, page_size: int) -> ResearchHistoryListResponse:
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(50, int(page_size)))
        items, total = self.repository.list_graph_records(
            user_id=user.id,
            page=safe_page,
            page_size=safe_page_size,
        )
        total_pages = (total + safe_page_size - 1) // safe_page_size if total > 0 else 0
        return ResearchHistoryListResponse(
            page=safe_page,
            page_size=safe_page_size,
            total=total,
            total_pages=total_pages,
            items=[
                ResearchHistoryListItem(
                    history_id=str(item.get("history_id") or ""),
                    research_type=self._normalize_research_type(item.get("research_type")),
                    search_record=str(item.get("search_record") or ""),
                    search_range=self._normalize_search_range(
                        item.get("search_range"),
                        research_type=item.get("research_type"),
                    ),
                    search_time=item.get("search_time"),
                    lineage=self._to_lineage_status(item.get("lineage")),
                )
                for item in items
            ],
        )

    def get_history_detail(self, *, user: UserProfile, history_id: str) -> ResearchHistoryDetailResponse | None:
        payload = self.repository.get_graph_record(user_id=user.id, history_id=history_id)
        if payload is None:
            return None
        raw_graph_payload = payload.get("graph_payload") or {}
        normalized_research_type = self._normalize_research_type(payload.get("research_type"))
        graph_payload: dict[str, Any] = {}
        landscape_graph: dict[str, Any] | None = None

        if isinstance(raw_graph_payload, dict) and isinstance(raw_graph_payload.get("graph"), dict):
            graph_payload = raw_graph_payload.get("graph") or {}
            if isinstance(raw_graph_payload.get("landscape_graph"), dict):
                landscape_graph = raw_graph_payload.get("landscape_graph")
        elif isinstance(raw_graph_payload, dict):
            graph_payload = raw_graph_payload
            if normalized_research_type == "domain" and self._looks_like_landscape_graph(raw_graph_payload):
                landscape_graph = raw_graph_payload

        graph = KnowledgeGraphResponse.model_validate(graph_payload or {})
        if normalized_research_type == "domain" and landscape_graph is None:
            landscape_graph = self._to_landscape_render_graph(
                graph=graph,
                search_record=str(payload.get("search_record") or ""),
            )
        return ResearchHistoryDetailResponse(
            history_id=str(payload.get("history_id") or ""),
            research_type=normalized_research_type,
            search_record=str(payload.get("search_record") or ""),
            search_range=self._normalize_search_range(
                payload.get("search_range"),
                research_type=normalized_research_type,
            ),
            search_time=payload.get("search_time"),
            lineage=self._to_lineage_status(payload.get("lineage")),
            graph=graph,
            landscape_graph=landscape_graph,
        )

    def record_lineage_status(
        self,
        *,
        user: UserProfile,
        graph_id: str,
        seed_paper_id: str,
        ancestor_count: int,
        descendant_count: int,
    ) -> bool:
        safe_graph_id = str(graph_id or "").strip()
        safe_seed_paper_id = str(seed_paper_id or "").strip()
        if not safe_graph_id or not safe_seed_paper_id:
            return False

        try:
            return self.repository.mark_lineage_generated(
                user_id=user.id,
                graph_id=safe_graph_id,
                seed_paper_id=safe_seed_paper_id,
                ancestor_count=max(0, self._safe_int(ancestor_count, fallback=0)),
                descendant_count=max(0, self._safe_int(descendant_count, fallback=0)),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed updating lineage status in research history.")
            return False

    @staticmethod
    def _normalize_research_type(raw_value: str | None) -> str:
        value = str(raw_value or "").strip().lower()
        if value in _VALID_RESEARCH_TYPES:
            return value
        return "unknown"

    @staticmethod
    def _normalize_search_range(raw_value: str | None, *, research_type: str | None) -> str:
        value = str(raw_value or "").strip()
        if value:
            return value
        normalized_type = str(research_type or "").strip().lower()
        if normalized_type == "domain":
            return "所有时间"
        return "不适用"

    @staticmethod
    def _format_domain_search_range(paper_range_years: int | None) -> str:
        try:
            years = int(paper_range_years) if paper_range_years is not None else 0
        except (TypeError, ValueError):
            years = 0
        if years > 0:
            return f"近 {years} 年"
        return "所有时间"

    @staticmethod
    def _to_lineage_status(raw_value: Any) -> ResearchHistoryLineageStatus:
        source = raw_value if isinstance(raw_value, dict) else {}
        return ResearchHistoryLineageStatus(
            generated=bool(source.get("generated")),
            ancestor_count=max(0, ResearchHistoryService._safe_int(source.get("ancestor_count"), fallback=0)),
            descendant_count=max(0, ResearchHistoryService._safe_int(source.get("descendant_count"), fallback=0)),
            seed_paper_id=str(source.get("seed_paper_id") or ""),
            updated_at=source.get("updated_at"),
        )

    @staticmethod
    def _to_history_graph(landscape: LandscapeResponse) -> KnowledgeGraphResponse:
        raw_graph = landscape.graph_data if isinstance(landscape.graph_data, dict) else {}
        nodes_raw = list(raw_graph.get("nodes") or [])
        edges_raw = list(raw_graph.get("edges") or [])

        nodes = [ResearchHistoryService._normalize_landscape_node(node) for node in nodes_raw if isinstance(node, dict)]
        edges = [
            ResearchHistoryService._normalize_landscape_edge(edge)
            for edge in edges_raw
            if isinstance(edge, dict)
        ]
        normalized_nodes = [node for node in nodes if node is not None]
        normalized_edges = [edge for edge in edges if edge is not None]

        paper_count = sum(1 for node in normalized_nodes if node.type == "paper")
        domain_count = sum(1 for node in normalized_nodes if node.type == "domain")
        entity_count = sum(1 for node in normalized_nodes if node.type == "entity")

        summary = str(landscape.trend_summary or "").strip()
        if not summary:
            summary = str(landscape.description or "").strip()
        if not summary:
            summary = f"{str(landscape.query or '').strip() or '领域研究'} 图谱"

        return KnowledgeGraphResponse(
            graph_id=str(landscape.landscape_id or "").strip() or "landscape-unknown",
            query=str(landscape.query or "").strip() or str(landscape.domain_name or "").strip(),
            paper_count=paper_count,
            entity_count=entity_count,
            domain_count=domain_count,
            nodes=normalized_nodes,
            edges=normalized_edges,
            build_steps=[],
            stored_in_neo4j=bool(landscape.stored_in_neo4j),
            summary=summary,
            generated_at=landscape.generated_at,
        )

    @staticmethod
    def _normalize_landscape_node(raw_node: dict[str, Any]) -> KnowledgeGraphNode | None:
        node_id = str(raw_node.get("id") or "").strip()
        if not node_id:
            return None

        raw_kind = str(raw_node.get("type") or raw_node.get("kind") or "").strip().lower()
        node_type = "entity"
        if raw_kind == "paper":
            node_type = "paper"
        elif raw_kind in {"domain", "seed"}:
            node_type = "domain"

        label = str(raw_node.get("label") or raw_node.get("name") or node_id).strip() or node_id
        size = ResearchHistoryService._safe_float(raw_node.get("size"), fallback=1.0)
        score = ResearchHistoryService._safe_float(
            raw_node.get("score", raw_node.get("relevance")),
            fallback=0.0,
        )
        size = max(1.0, size)
        score = max(0.0, min(score, 1.0))

        return KnowledgeGraphNode(
            id=node_id,
            label=label,
            type=node_type,
            size=size,
            score=score,
            paper_id=node_id if node_type == "paper" else None,
            meta=ResearchHistoryService._stringify_meta(raw_node.get("meta")),
        )

    @staticmethod
    def _normalize_landscape_edge(raw_edge: dict[str, Any]) -> KnowledgeGraphEdge | None:
        source = str(raw_edge.get("source") or "").strip()
        target = str(raw_edge.get("target") or "").strip()
        if not source or not target:
            return None

        raw_relation = str(raw_edge.get("relation") or "").strip().lower()
        if not raw_relation:
            raw_kind = str(raw_edge.get("kind") or "").strip().lower()
            if raw_kind == "related":
                raw_relation = "belongs_to"
            elif raw_kind == "center":
                raw_relation = "covers"
            else:
                raw_relation = "related"

        if raw_relation not in {"mentions", "belongs_to", "related", "covers"}:
            raw_relation = "related"

        weight = ResearchHistoryService._safe_float(
            raw_edge.get("weight", raw_edge.get("relevance")),
            fallback=0.25,
        )
        weight = max(0.0, min(weight, 1.0))

        return KnowledgeGraphEdge(
            source=source,
            target=target,
            relation=raw_relation,
            weight=weight,
            meta=ResearchHistoryService._stringify_meta(raw_edge.get("meta")),
        )

    @staticmethod
    def _stringify_meta(raw_meta: Any) -> dict[str, str]:
        if not isinstance(raw_meta, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, value in raw_meta.items():
            clean_key = str(key).strip()
            if not clean_key:
                continue
            if isinstance(value, str):
                clean_value = value.strip()
            elif value is None:
                clean_value = ""
            elif isinstance(value, (int, float, bool)):
                clean_value = str(value)
            else:
                try:
                    clean_value = json.dumps(value, ensure_ascii=False)
                except TypeError:
                    clean_value = str(value)
            if clean_value:
                normalized[clean_key] = clean_value
        return normalized

    @staticmethod
    def _safe_float(raw_value: Any, *, fallback: float) -> float:
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _safe_int(raw_value: Any, *, fallback: int) -> int:
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _looks_like_landscape_graph(raw_payload: dict[str, Any]) -> bool:
        nodes = raw_payload.get("nodes")
        edges = raw_payload.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return False
        return True

    @staticmethod
    def _to_landscape_render_graph(
        *,
        graph: KnowledgeGraphResponse,
        search_record: str,
    ) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        for node in graph.nodes:
            node_id = str(node.id or "").strip()
            if not node_id:
                continue
            if node_id.startswith("seed:"):
                kind = "seed"
            elif node.type == "domain":
                kind = "domain"
            elif node.type == "paper":
                kind = "paper"
            else:
                continue

            relevance = ResearchHistoryService._safe_float(
                (node.meta or {}).get("relevance"),
                fallback=node.score,
            )
            nodes.append(
                {
                    "id": node_id,
                    "name": node.label,
                    "label": node.label,
                    "kind": kind,
                    "relevance": max(0.0, min(relevance, 1.0)),
                    "score": max(0.0, min(ResearchHistoryService._safe_float(node.score, fallback=0.0), 1.0)),
                    "size": max(1.0, ResearchHistoryService._safe_float(node.size, fallback=1.0)),
                    "meta": dict(node.meta or {}),
                }
            )

        for index, edge in enumerate(graph.edges):
            source = str(edge.source or "").strip()
            target = str(edge.target or "").strip()
            if not source or not target:
                continue
            kind = "center" if edge.relation == "covers" else "related"
            relevance = max(0.0, min(ResearchHistoryService._safe_float(edge.weight, fallback=0.25), 1.0))
            edges.append(
                {
                    "id": f"history-edge-{index}",
                    "source": source,
                    "target": target,
                    "kind": kind,
                    "relevance": relevance,
                    "weight": relevance,
                    "meta": dict(edge.meta or {}),
                }
            )

        return {
            "title": f"{str(graph.query or search_record).strip() or '领域研究'} 领域图谱",
            "query": str(graph.query or search_record).strip(),
            "nodes": nodes,
            "edges": edges,
            "counts": {
                "seed": sum(1 for node in nodes if node.get("kind") == "seed"),
                "domain": sum(1 for node in nodes if node.get("kind") == "domain"),
                "paper": sum(1 for node in nodes if node.get("kind") == "paper"),
                "edges": len(edges),
            },
        }


@lru_cache
def get_research_history_service() -> ResearchHistoryService:
    return ResearchHistoryService()
