from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from itertools import combinations
import json
import logging
import math
import re
from time import perf_counter
from typing import Any
from urllib.parse import quote_plus
from uuid import uuid4

from external.openalex import OpenAlexClient, OpenAlexClientError
from external.semantic_scholar import (
    SemanticScholarClient,
    SemanticScholarClientError,
)
from core.domain_explorer import DomainExplorer
from core.llm_client import chat, get_client, is_configured
from core.settings import get_settings
from models.schemas import (
    BuildTraceStep,
    KnowledgeGraphBuildRequest,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeGraphRetrievalResponse,
    KnowledgeGraphRetrieveRequest,
    KnowledgeGraphResponse,
    RetrievedPaper,
    RetrievalTraceStep,
)
from repositories.neo4j_repository import Neo4jRepository, get_neo4j_repository
from services.retrieval.multi_source_retriever import MultiSourceRetriever

logger = logging.getLogger(__name__)


class GraphRAGService:
    """First-step GraphRAG pipeline: retrieval, entity extraction, graph build, Neo4j write."""

    _STOPWORDS = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "using",
        "based",
        "study",
        "paper",
        "approach",
        "method",
        "model",
        "towards",
        "analysis",
        "results",
        "through",
        "their",
        "our",
        "they",
        "are",
        "were",
        "been",
        "can",
        "new",
        "via",
    }

    def __init__(self, neo4j_repo: Neo4jRepository | None = None) -> None:
        self.semantic = SemanticScholarClient()
        self.openalex = OpenAlexClient()
        self.domain_explorer = DomainExplorer(
            semantic_client=self.semantic,
            openalex_client=self.openalex,
        )
        self.retriever = MultiSourceRetriever(
            semantic_client=self.semantic,
            openalex_client=self.openalex,
        )
        self.neo4j_repo = neo4j_repo or get_neo4j_repository()
        self.settings = get_settings()
        self._embedding_client = None
        self._embedding_cache: dict[str, list[float]] = {}
        self._paper_relation_cache: dict[str, dict[str, list[str]]] = {}
        self._embedding_unavailable = False

    def build_knowledge_graph(self, request: KnowledgeGraphBuildRequest) -> KnowledgeGraphResponse:
        graph_id = f"kg-{uuid4().hex[:12]}"
        if request.prefetched_papers:
            papers = [paper.model_dump() for paper in request.prefetched_papers]
        else:
            retrieval_payload = self._retrieve_papers_with_trace(request.query, request.max_papers)
            papers = retrieval_payload["selected_papers"]

        build_start = perf_counter()
        paper_nodes, entity_nodes, domain_nodes, edges = self._build_graph_components(
            papers=papers,
            max_entities_per_paper=request.max_entities_per_paper,
            query=request.query,
        )
        build_elapsed = perf_counter() - build_start

        nodes = paper_nodes + entity_nodes + domain_nodes
        store_start = perf_counter()
        stored = self.neo4j_repo.store_graph(
            graph_id=graph_id,
            query=request.query,
            nodes=[node.model_dump() for node in nodes],
            edges=[edge.model_dump() for edge in edges],
        )
        store_elapsed = perf_counter() - store_start

        build_steps = [
            BuildTraceStep.model_validate(
                self._build_graph_trace_step(
                    phase="build_extract",
                    title="建图与实体关系抽取",
                    detail=(
                        f"已构建 {len(paper_nodes)} 个论文节点、{len(entity_nodes)} 个实体节点、"
                        f"{len(domain_nodes)} 个领域节点，共生成 {len(edges)} 条关系边。"
                    ),
                    elapsed_seconds=build_elapsed,
                )
            ),
            BuildTraceStep.model_validate(
                self._build_graph_trace_step(
                    phase="store_graph",
                    title="图谱落库与回读准备",
                    detail=(
                        f"已写入 Neo4j（graph_id={graph_id}），可执行回读验证。"
                        if stored
                        else "Neo4j 不可用，已保留实时构建结果并跳过落库。"
                    ),
                    status="done" if stored else "fallback",
                    elapsed_seconds=store_elapsed,
                )
            ),
        ]

        summary = self._build_summary(
            query=request.query,
            paper_count=len(paper_nodes),
            entity_count=len(entity_nodes),
            domain_count=len(domain_nodes),
            edge_count=len(edges),
            stored=stored,
        )

        return KnowledgeGraphResponse(
            graph_id=graph_id,
            query=request.query,
            paper_count=len(paper_nodes),
            entity_count=len(entity_nodes),
            domain_count=len(domain_nodes),
            nodes=nodes,
            edges=edges,
            build_steps=build_steps,
            stored_in_neo4j=stored,
            summary=summary,
            generated_at=datetime.now(timezone.utc),
        )

    def fetch_knowledge_graph(self, graph_id: str) -> KnowledgeGraphResponse:
        payload = self.neo4j_repo.fetch_graph(graph_id)
        if payload is None:
            raise ValueError(f"graph_id not found or neo4j unavailable: {graph_id}")

        nodes = [KnowledgeGraphNode.model_validate(item) for item in payload.get("nodes", [])]
        edges = [KnowledgeGraphEdge.model_validate(item) for item in payload.get("edges", [])]

        paper_count = sum(1 for node in nodes if node.type == "paper")
        entity_count = sum(1 for node in nodes if node.type == "entity")
        domain_count = sum(1 for node in nodes if node.type == "domain")
        summary = (
            f"从 Neo4j 读取图谱“{graph_id}”，包含 {paper_count} 篇论文、"
            f"{entity_count} 个实体、{domain_count} 个领域和 {len(edges)} 条关系。"
        )
        return KnowledgeGraphResponse(
            graph_id=graph_id,
            query=str(payload.get("query") or ""),
            paper_count=paper_count,
            entity_count=entity_count,
            domain_count=domain_count,
            nodes=nodes,
            edges=edges,
            stored_in_neo4j=True,
            summary=summary,
            generated_at=datetime.now(timezone.utc),
        )

    def get_neo4j_status(self) -> bool:
        return self.neo4j_repo.is_available()

    def retrieve_papers(self, request: KnowledgeGraphRetrieveRequest) -> KnowledgeGraphRetrievalResponse:
        retrieval_payload = self._retrieve_papers_with_trace(
            query=request.query,
            max_papers=request.max_papers,
            input_type=request.input_type,
            quick_mode=request.quick_mode,
            paper_range_years=request.paper_range_years,
        )
        papers = [RetrievedPaper.model_validate(item) for item in retrieval_payload["selected_papers"]]
        steps = [RetrievalTraceStep.model_validate(item) for item in retrieval_payload["steps"]]
        resolved_query = str(retrieval_payload.get("query") or request.query).strip() or request.query
        return KnowledgeGraphRetrievalResponse(
            query=resolved_query,
            provider=str(retrieval_payload["provider"]),
            providers_used=[str(item) for item in (retrieval_payload.get("providers_used") or []) if str(item).strip()],
            provider_stats=list(retrieval_payload.get("provider_stats") or []),
            candidate_count=int(retrieval_payload["candidate_count"]),
            selected_count=len(papers),
            papers=papers,
            steps=steps,
            generated_at=datetime.now(timezone.utc),
        )

    def _retrieve_papers(
        self,
        query: str,
        max_papers: int,
        input_type: str = "domain",
        quick_mode: bool = False,
        paper_range_years: int | None = None,
    ) -> list[dict[str, Any]]:
        payload = self._retrieve_papers_with_trace(
            query=query,
            max_papers=max_papers,
            input_type=input_type,
            quick_mode=quick_mode,
            paper_range_years=paper_range_years,
        )
        return payload["selected_papers"]

    def _retrieve_papers_with_trace(
        self,
        query: str,
        max_papers: int,
        input_type: str = "domain",
        quick_mode: bool = False,
        paper_range_years: int | None = None,
    ) -> dict[str, Any]:
        normalized_input_type = str(input_type or "domain").strip().lower()
        if normalized_input_type in {"arxiv_id", "doi"}:
            return self._retrieve_papers_from_seed_input_with_trace(
                input_type=normalized_input_type,
                input_value=query,
                max_papers=max_papers,
                quick_mode=quick_mode,
                paper_range_years=paper_range_years,
            )
        normalized_query_payload = self._normalize_domain_query(query)
        normalized_query = str(normalized_query_payload.get("canonical_query") or query).strip() or str(query or "").strip()
        payload = self._retrieve_papers_from_query_with_trace(
            query=normalized_query,
            max_papers=max_papers,
            paper_range_years=paper_range_years,
            preferred_provider="openalex" if quick_mode else "semantic_scholar",
            domain_authority_mode=normalized_input_type == "domain",
        )
        payload["query"] = normalized_query
        return self._with_normalized_domain_query_trace(
            payload=payload,
            normalized_query_payload=normalized_query_payload,
        )

    def _normalize_domain_query(self, query: str) -> dict[str, Any]:
        safe_query = re.sub(r"\s+", " ", str(query or "").strip())
        if not safe_query:
            return {
                "original_query": "",
                "corrected_query": "",
                "translated_query": "",
                "canonical_query": "",
                "used_llm": False,
                "was_corrected": False,
            }

        try:
            normalized = asyncio.run(self.domain_explorer.normalize_user_query(safe_query))
            if isinstance(normalized, dict):
                return normalized
        except RuntimeError:
            # A running event loop can appear in non-standard embedding scenarios.
            logger.debug("event_loop_running_during_query_normalization", exc_info=True)
        except Exception:  # noqa: BLE001
            logger.exception("domain query normalization failed; fallback to raw query")

        fallback_query = str(self.domain_explorer._normalize_query_for_search(safe_query) or safe_query).strip() or safe_query
        return {
            "original_query": safe_query,
            "corrected_query": fallback_query,
            "translated_query": fallback_query,
            "canonical_query": fallback_query,
            "used_llm": False,
            "was_corrected": fallback_query != safe_query,
        }

    def _with_normalized_domain_query_trace(
        self,
        *,
        payload: dict[str, Any],
        normalized_query_payload: dict[str, Any],
    ) -> dict[str, Any]:
        steps = list(payload.get("steps") or [])
        if not steps:
            return payload

        original_query = str(normalized_query_payload.get("original_query") or "").strip()
        canonical_query = str(normalized_query_payload.get("canonical_query") or "").strip()
        corrected_query = str(normalized_query_payload.get("corrected_query") or "").strip()
        translated_query = str(normalized_query_payload.get("translated_query") or "").strip()
        was_corrected = bool(normalized_query_payload.get("was_corrected"))
        if not original_query:
            return payload

        lead_step = dict(steps[0])
        if was_corrected and canonical_query:
            normalization_mode = "中文翻译+纠错" if bool(re.search(r"[\u4e00-\u9fff]", original_query)) else "英文纠错"
            lead_step["title"] = "检索词标准化与搜索规划"
            lead_step["detail"] = (
                f"输入标准化完成（{normalization_mode}）：原始“{original_query}” -> 当前检索“{canonical_query}”。"
                f" 纠错结果“{corrected_query or original_query}”，英文检索词“{translated_query or canonical_query}”。"
            )
        else:
            lead_step["title"] = "检索词检查与搜索规划"
            lead_step["detail"] = f"已检查检索词“{original_query}”，并直接用于学术检索。"

        steps[0] = lead_step
        return {
            **payload,
            "steps": steps,
        }

    def _retrieve_papers_from_seed_input_with_trace(
        self,
        *,
        input_type: str,
        input_value: str,
        max_papers: int,
        quick_mode: bool = False,
        paper_range_years: int | None = None,
    ) -> dict[str, Any]:
        safe_value = self._normalize_seed_input_value(input_type=input_type, input_value=input_value)
        if not safe_value:
            safe_value = input_value.strip()
        safe_max = max(1, max_papers)
        candidate_limit = min(220, max(safe_max + 36, safe_max * 16))
        normalized_range = self._normalize_paper_range_years(paper_range_years)
        steps: list[dict[str, Any]] = []
        preferred_seed_provider = "openalex" if quick_mode else "semantic_scholar"

        search_detail, search_links = self._seed_search_trace(
            input_type=input_type,
            input_value=safe_value,
            preferred_provider=preferred_seed_provider,
        )
        steps.append(
            self._build_retrieval_step(
                phase="search_web",
                title="种子论文定位与请求构造",
                detail=search_detail,
                provider=preferred_seed_provider,
                count=0,
                links=search_links,
                elapsed_seconds=0.0,
            )
        )

        if self.settings.graphrag_force_mock:
            candidates = self._fallback_papers(query=safe_value, max_papers=candidate_limit)
            candidates, range_filter_stats = self._apply_paper_year_range(
                candidates,
                paper_range_years=normalized_range,
            )
            selected_papers, filter_stats = self._filter_and_rank_papers(
                candidates,
                safe_max,
                safe_value,
                ranking_profile="seed_lineage",
            )
            range_hint = self._build_year_range_hint(normalized_range, range_filter_stats)
            steps.append(
                self._build_retrieval_step(
                    phase="retrieve",
                    title="候选论文聚合",
                    detail=f"已启用 mock 模式，生成 {len(candidates)} 条候选论文。{range_hint}",
                    status="fallback",
                    provider="mock",
                    count=len(candidates),
                    links=[],
                    elapsed_seconds=0.0,
                )
            )
            steps.append(
                self._build_retrieval_step(
                    phase="filter",
                    title="候选筛选与排序",
                    detail=(
                        f"输入 {filter_stats['input']} 条，去重后 {filter_stats['deduped']} 条，"
                        f"按相关度/引用数/新近性筛选保留 {filter_stats['selected']} 条。"
                    ),
                    provider="mock",
                    count=len(selected_papers),
                    links=[],
                    elapsed_seconds=filter_stats["elapsed_seconds"],
                )
            )
            return {
                "query": safe_value,
                "provider": "mock",
                "providers_used": [],
                "provider_stats": [],
                "candidate_count": len(candidates),
                "selected_papers": selected_papers,
                "steps": steps,
            }

        fetch_start = perf_counter()
        seed_lookup: dict[str, Any] = {}
        seed_provider_stats: list[dict[str, Any]] = []
        seed_providers_used: list[str] = []
        try:
            seed_lookup = self.retriever.fetch_seed_paper(
                input_type=input_type,
                input_value=safe_value,
                reference_limit=candidate_limit,
                citation_limit=candidate_limit,
                preferred_provider=preferred_seed_provider,
            )
            seed_provider_stats = list(seed_lookup.get("source_stats") or [])
            seed_providers_used = [
                str(item).strip()
                for item in (seed_lookup.get("providers_used") or [])
                if str(item).strip()
            ]
            seed_paper = dict(seed_lookup.get("seed_paper") or {})
            if not seed_paper:
                raise ValueError(f"seed_paper_not_found: {input_type}:{safe_value}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("seed retrieval failed for input_type=%s, value=%s: %s", input_type, safe_value, exc)
            fallback_payload = self._retrieve_papers_from_query_with_trace(
                query=safe_value,
                max_papers=safe_max,
                paper_range_years=normalized_range,
                preferred_provider=preferred_seed_provider,
            )
            fallback_payload_steps = fallback_payload.get("steps") or []
            fallback_payload_steps.insert(
                0,
                self._build_retrieval_step(
                    phase="search_web",
                    title="种子论文定位与请求构造",
                    detail="种子论文定位失败，已自动降级为关键词检索。",
                    status="fallback",
                    provider=preferred_seed_provider,
                    count=0,
                    links=search_links,
                    elapsed_seconds=0.0,
                ),
            )
            fallback_payload["provider_stats"] = self._merge_source_stats(
                seed_provider_stats,
                list(fallback_payload.get("provider_stats") or []),
            )
            fallback_payload["providers_used"] = self._merge_provider_list(
                seed_providers_used,
                list(fallback_payload.get("providers_used") or []),
            )
            fallback_payload["steps"] = fallback_payload_steps
            return fallback_payload

        seed_title = str(seed_paper.get("title") or "").strip() or safe_value
        seed_paper_id = str(seed_paper.get("paper_id") or "").strip()
        inferred_provider = self._infer_seed_provider(seed_paper)
        provider_used = inferred_provider if inferred_provider in {"semantic_scholar", "openalex", "arxiv"} else preferred_seed_provider

        candidates = self._collect_seed_candidates(seed_paper, candidate_limit=candidate_limit)
        related_references = len(seed_paper.get("references") or [])
        related_citations = len(seed_paper.get("citations") or [])
        expansion_added = 0
        sparse_threshold = max(3, min(8, safe_max // 2))
        if len(candidates) <= sparse_threshold:
            expansion_limit = min(candidate_limit, max(safe_max * 5, 36))
            expansion_payload = self.retriever.search_papers(
                query=seed_title,
                limit=expansion_limit,
                preferred_provider=preferred_seed_provider,
            )
            expansion_papers = list(expansion_payload.get("papers") or [])
            if expansion_papers:
                expanded = self._merge_candidate_lists(
                    primary=candidates,
                    secondary=expansion_papers,
                    limit=candidate_limit,
                )
                expansion_added = max(0, len(expanded) - len(candidates))
                candidates = expanded
            seed_provider_stats = self._merge_source_stats(
                seed_provider_stats,
                list(expansion_payload.get("source_stats") or []),
            )
            seed_providers_used = self._merge_provider_list(
                seed_providers_used,
                list(expansion_payload.get("providers_used") or []),
            )

        if not candidates:
            provider_used = "mock"
            candidates = self._fallback_papers(query=seed_title, max_papers=candidate_limit)

        candidates, range_filter_stats = self._apply_paper_year_range(
            candidates,
            paper_range_years=normalized_range,
            preserve_paper_id=seed_paper_id,
        )
        range_hint = self._build_year_range_hint(normalized_range, range_filter_stats)

        retrieve_status = "done" if provider_used in {"semantic_scholar", "openalex", "arxiv"} else "fallback"
        trace_provider = "+".join(seed_providers_used) if seed_providers_used else provider_used
        steps.append(
            self._build_retrieval_step(
                phase="retrieve",
                title="候选论文聚合",
                detail=(
                    f"已定位种子论文《{seed_title}》，聚合参考文献 {related_references} 篇、"
                    f"被引文献 {related_citations} 篇。"
                    f"{' 已补充相关论文 ' + str(expansion_added) + ' 篇。' if expansion_added > 0 else ''}"
                    f"{range_hint}"
                ),
                status=retrieve_status,
                provider=trace_provider,
                count=len(candidates),
                links=[],
                elapsed_seconds=perf_counter() - fetch_start,
            )
        )

        selected_papers, filter_stats = self._filter_and_rank_papers(
            candidates,
            safe_max,
            seed_title or safe_value,
            ranking_profile="seed_lineage",
        )
        selected_papers = self._ensure_seed_first(selected_papers, seed_paper_id)
        steps.append(
            self._build_retrieval_step(
                phase="filter",
                title="候选筛选与排序",
                detail=(
                    f"输入 {filter_stats['input']} 条，去重后 {filter_stats['deduped']} 条，"
                    f"按相关度/引用数/新近性筛选保留 {filter_stats['selected']} 条。"
                ),
                provider=trace_provider,
                count=len(selected_papers),
                links=[],
                elapsed_seconds=filter_stats["elapsed_seconds"],
            )
        )
        return {
            "query": seed_title or safe_value,
            "provider": provider_used,
            "providers_used": seed_providers_used,
            "provider_stats": seed_provider_stats,
            "candidate_count": len(candidates),
            "selected_papers": selected_papers,
            "steps": steps,
        }

    @staticmethod
    def _merge_provider_list(primary: list[str], secondary: list[str]) -> list[str]:
        merged: list[str] = []
        for raw in [*(primary or []), *(secondary or [])]:
            value = str(raw or "").strip()
            if not value or value in merged:
                continue
            merged.append(value)
        return merged

    @staticmethod
    def _merge_source_stats(
        primary: list[dict[str, Any]],
        secondary: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for item in [*(primary or []), *(secondary or [])]:
            provider = str(item.get("provider") or "").strip()
            if not provider:
                continue
            status = "done" if str(item.get("status") or "").strip().lower() == "done" else "fallback"
            count = GraphRAGService._safe_int(item.get("count"))
            elapsed_ms = GraphRAGService._safe_int(item.get("elapsed_ms"))
            error = str(item.get("error") or "").strip()

            current = merged.get(provider)
            if current is None:
                merged[provider] = {
                    "provider": provider,
                    "status": status,
                    "count": count,
                    "elapsed_ms": elapsed_ms,
                    "error": "" if status == "done" else error,
                }
                continue

            current["status"] = "done" if "done" in {current.get("status"), status} else "fallback"
            current["count"] = max(GraphRAGService._safe_int(current.get("count")), count)
            current["elapsed_ms"] = max(GraphRAGService._safe_int(current.get("elapsed_ms")), elapsed_ms)
            if current["status"] == "done":
                current["error"] = ""
            elif not str(current.get("error") or "").strip() and error:
                current["error"] = error

        return list(merged.values())

    def _fetch_seed_document_semantic(
        self,
        *,
        input_type: str,
        input_value: str,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any]:
        if input_type == "arxiv_id":
            paper = self.semantic.fetch_paper_by_arxiv_id(
                input_value,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
            return {"seed_paper": paper}
        if input_type == "doi":
            paper = self.semantic.fetch_paper_by_doi(
                input_value,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
            return {"seed_paper": paper}
        raise ValueError(f"unsupported seed input_type: {input_type}")

    def _fetch_seed_document_openalex(
        self,
        *,
        input_type: str,
        input_value: str,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any]:
        paper: dict[str, Any] | None = None
        if input_type == "arxiv_id":
            paper = self.openalex.fetch_paper_by_arxiv_id(
                input_value,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        elif input_type == "doi":
            paper = self.openalex.fetch_paper_by_doi(
                input_value,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        else:
            raise ValueError(f"unsupported seed input_type: {input_type}")

        if not paper:
            raise OpenAlexClientError(f"openalex_seed_not_found: {input_value}")
        return {"seed_paper": paper}

    def _fetch_seed_document_by_provider(
        self,
        *,
        provider: str,
        input_type: str,
        input_value: str,
        reference_limit: int,
        citation_limit: int,
    ) -> dict[str, Any]:
        normalized_provider = str(provider or "semantic_scholar").strip().lower()
        if normalized_provider == "openalex":
            return self._fetch_seed_document_openalex(
                input_type=input_type,
                input_value=input_value,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        return self._fetch_seed_document_semantic(
            input_type=input_type,
            input_value=input_value,
            reference_limit=reference_limit,
            citation_limit=citation_limit,
        )

    def _retrieve_papers_from_query_with_trace(
        self,
        query: str,
        max_papers: int,
        paper_range_years: int | None = None,
        preferred_provider: str = "semantic_scholar",
        domain_authority_mode: bool = False,
    ) -> dict[str, Any]:
        safe_query = query.strip()
        safe_max = max(1, max_papers)
        candidate_limit = min(180, max(safe_max + 20, safe_max * 6)) if domain_authority_mode else min(120, max(safe_max + 20, safe_max * 6))
        normalized_range = self._normalize_paper_range_years(paper_range_years)
        primary_provider = self._normalize_search_provider(preferred_provider)
        steps: list[dict[str, Any]] = []
        web_links = [
            f"https://api.semanticscholar.org/graph/v1/paper/search?query={quote_plus(safe_query)}",
            f"https://api.openalex.org/works?search={quote_plus(safe_query)}",
        ]
        steps.append(
            self._build_retrieval_step(
                phase="search_web",
                title="LLM 检索规划与网页搜索",
                detail=(
                    "已构造代表性论文检索策略（核心主题 / survey / benchmark / 高被引），并向多学术索引发起请求。"
                    if domain_authority_mode
                    else "已构造学术检索查询，并向外部学术索引发起请求。"
                ),
                provider="semantic_scholar+openalex",
                count=0,
                links=web_links,
                elapsed_seconds=0.0,
            )
        )

        if self.settings.graphrag_force_mock:
            candidates = self._fallback_papers(query=safe_query, max_papers=candidate_limit)
            candidates, range_filter_stats = self._apply_paper_year_range(
                candidates,
                paper_range_years=normalized_range,
            )
            range_hint = self._build_year_range_hint(normalized_range, range_filter_stats)
            steps.append(
                self._build_retrieval_step(
                    phase="retrieve",
                    title="候选论文检索",
                    detail=(
                        f"已启用 mock 模式，生成 {len(candidates)} 条候选论文。{range_hint}"
                        if not domain_authority_mode
                        else f"已启用 mock 模式，模拟代表性候选 {len(candidates)} 条。{range_hint}"
                    ),
                    status="fallback",
                    provider="mock",
                    count=len(candidates),
                    links=[],
                    elapsed_seconds=0.0,
                )
            )
            selected_papers, filter_stats = self._filter_and_rank_papers(
                candidates,
                safe_max,
                safe_query,
                ranking_profile="domain_authority" if domain_authority_mode else "balanced",
                paper_range_years=normalized_range,
            )
            steps.append(
                self._build_retrieval_step(
                    phase="filter",
                    title="候选筛选与排序",
                    detail=(
                        (
                            f"输入 {filter_stats['input']} 条，去重后 {filter_stats['deduped']} 条，"
                            f"按代表性/引用数/相关性筛选保留 {filter_stats['selected']} 条。"
                        )
                        if domain_authority_mode
                        else (
                            f"输入 {filter_stats['input']} 条，去重后 {filter_stats['deduped']} 条，"
                            f"按相关度/引用数/新近性筛选保留 {filter_stats['selected']} 条。"
                        )
                    ),
                    provider="mock",
                    count=len(selected_papers),
                    links=[],
                    elapsed_seconds=0.0,
                )
            )
            return {
                "query": safe_query,
                "provider": "mock",
                "providers_used": [],
                "provider_stats": [],
                "candidate_count": len(candidates),
                "selected_papers": selected_papers,
                "steps": steps,
            }

        if domain_authority_mode:
            search_result = self._search_domain_authority_candidates(
                query=safe_query,
                limit=candidate_limit,
                preferred_provider=primary_provider,
            )
        else:
            search_result = self.retriever.search_papers(
                query=safe_query,
                limit=candidate_limit,
                preferred_provider=primary_provider,
            )
        provider_used = str(search_result.get("provider") or "mock")
        providers_used = [
            str(item).strip()
            for item in (search_result.get("providers_used") or [])
            if str(item).strip()
        ]
        provider_stats = list(search_result.get("source_stats") or [])
        candidate_papers = list(search_result.get("papers") or [])
        if not candidate_papers:
            provider_used = "mock"
            candidate_papers = self._fallback_papers(query=safe_query, max_papers=candidate_limit)

        candidate_papers, range_filter_stats = self._apply_paper_year_range(
            candidate_papers,
            paper_range_years=normalized_range,
        )
        if domain_authority_mode and normalized_range is not None:
            candidate_papers = self._ensure_recent_year_coverage_candidates(
                query=safe_query,
                papers=candidate_papers,
                paper_range_years=normalized_range,
                preferred_provider=primary_provider,
            )
        range_hint = self._build_year_range_hint(normalized_range, range_filter_stats)
        retrieve_status = "done" if provider_used != "mock" else "fallback"
        retrieve_elapsed = float(search_result.get("elapsed_seconds") or 0.0)
        used_fallback = bool(search_result.get("used_fallback", False))

        if provider_used == "mock":
            retrieve_detail = f"外部检索失败，已降级为 mock 数据（{len(candidate_papers)} 条候选）。{range_hint}"
        else:
            query_variants = list(search_result.get("query_variants") or [])
            variant_hint = (
                f" 基于 {len(query_variants)} 个主题扩展查询聚合结果。"
                if domain_authority_mode and len(query_variants) > 1
                else ""
            )
            if len(providers_used) > 1:
                retrieve_detail = (
                    f"并行检索已完成，多个学术索引共返回 {len(candidate_papers)} 条候选论文。"
                    f"{variant_hint}{range_hint}"
                )
            elif used_fallback and provider_used != primary_provider:
                retrieve_detail = (
                    f"主检索通道暂不可用，"
                    f"已自动切换备用通道，返回 {len(candidate_papers)} 条候选论文。{variant_hint}{range_hint}"
                )
            else:
                retrieve_detail = f"检索通道返回 {len(candidate_papers)} 条候选论文。{variant_hint}{range_hint}"

        trace_provider = "+".join(providers_used) if providers_used else provider_used
        steps.append(
            self._build_retrieval_step(
                phase="retrieve",
                title="候选论文检索",
                detail=retrieve_detail,
                status=retrieve_status,
                provider=trace_provider,
                count=len(candidate_papers),
                links=[],
                elapsed_seconds=retrieve_elapsed,
            )
        )

        selected_papers, filter_stats = self._filter_and_rank_papers(
            candidate_papers,
            safe_max,
            safe_query,
            ranking_profile="domain_authority" if domain_authority_mode else "balanced",
            paper_range_years=normalized_range,
        )
        steps.append(
            self._build_retrieval_step(
                phase="filter",
                title="候选筛选与排序",
                detail=(
                    (
                        f"输入 {filter_stats['input']} 条，去重后 {filter_stats['deduped']} 条，"
                        f"按代表性/引用数/相关性筛选保留 {filter_stats['selected']} 条。"
                    )
                    if domain_authority_mode
                    else (
                        f"输入 {filter_stats['input']} 条，去重后 {filter_stats['deduped']} 条，"
                        f"按相关度/引用数/新近性筛选保留 {filter_stats['selected']} 条。"
                    )
                ),
                provider=trace_provider,
                count=len(selected_papers),
                links=[],
                elapsed_seconds=filter_stats["elapsed_seconds"],
            )
        )
        return {
            "query": safe_query,
            "provider": provider_used,
            "providers_used": providers_used,
            "provider_stats": provider_stats,
            "candidate_count": len(candidate_papers),
            "selected_papers": selected_papers,
            "steps": steps,
        }

    def _ensure_recent_year_coverage_candidates(
        self,
        *,
        query: str,
        papers: list[dict[str, Any]],
        paper_range_years: int | None,
        preferred_provider: str,
    ) -> list[dict[str, Any]]:
        normalized_range = self._normalize_paper_range_years(paper_range_years)
        if normalized_range is None or normalized_range <= 1:
            return papers

        current_year = datetime.now(timezone.utc).year
        target_years = list(range(max(1, current_year - normalized_range), current_year + 1))
        merged = self._merge_candidate_lists(
            primary=[],
            secondary=list(papers or []),
            limit=max(220, len(papers or []) + 80),
        )
        if not merged:
            return merged

        existing_years = {
            self._safe_int(item.get("year"))
            for item in merged
            if self._safe_int(item.get("year")) > 0
        }
        missing_years = [year for year in target_years if year not in existing_years]
        if not missing_years:
            return merged

        for year in missing_years:
            year_queries = [
                f"{query} {year} seminal",
                f"{query} {year} survey",
                f"{query} {year}",
            ]
            found = False
            for year_query in year_queries:
                payload = self.retriever.search_papers(
                    query=year_query,
                    limit=32,
                    preferred_provider=preferred_provider,
                )
                year_candidates = list(payload.get("papers") or [])
                if not year_candidates:
                    continue
                year_candidates, _ = self._apply_paper_year_range(
                    year_candidates,
                    paper_range_years=normalized_range,
                )
                year_candidates = [
                    candidate
                    for candidate in year_candidates
                    if self._safe_int(candidate.get("year")) == year
                ]
                if not year_candidates:
                    continue
                merged = self._merge_candidate_lists(
                    primary=merged,
                    secondary=year_candidates,
                    limit=max(240, len(merged) + 56),
                )
                found = True
                break
            if not found:
                continue

        return merged

    def _search_domain_authority_candidates(
        self,
        *,
        query: str,
        limit: int,
        preferred_provider: str,
    ) -> dict[str, Any]:
        safe_query = str(query or "").strip()
        safe_limit = max(1, min(limit, 180))
        query_variants = self._build_domain_authority_queries(safe_query)
        per_query_limit = max(18, min(60, max(24, safe_limit // max(1, len(query_variants)))))

        merged_candidates: list[dict[str, Any]] = []
        merged_stats: list[dict[str, Any]] = []
        merged_providers: list[str] = []
        total_elapsed = 0.0
        used_fallback = False

        for expansion_query in query_variants:
            payload = self.retriever.search_papers(
                query=expansion_query,
                limit=per_query_limit,
                preferred_provider=preferred_provider,
            )
            total_elapsed += float(payload.get("elapsed_seconds") or 0.0)
            used_fallback = used_fallback or bool(payload.get("used_fallback"))
            merged_stats = self._merge_source_stats(merged_stats, list(payload.get("source_stats") or []))
            merged_providers = self._merge_provider_list(
                merged_providers,
                list(payload.get("providers_used") or []),
            )
            merged_candidates = self._merge_candidate_lists(
                primary=merged_candidates,
                secondary=list(payload.get("papers") or []),
                limit=safe_limit,
            )
            if len(merged_candidates) >= safe_limit:
                break

        if not merged_candidates:
            return {
                "provider": "mock",
                "status": "fallback",
                "papers": self._fallback_papers(query=safe_query, max_papers=safe_limit),
                "elapsed_seconds": total_elapsed,
                "used_fallback": True,
                "primary_provider": preferred_provider,
                "providers_used": merged_providers,
                "source_stats": merged_stats,
                "query_variants": query_variants,
            }

        provider = self._merge_provider_labels(set(merged_providers))
        if provider == "mock":
            provider = str(preferred_provider or "semantic_scholar").strip() or "semantic_scholar"
        return {
            "provider": provider,
            "status": "fallback" if used_fallback else "done",
            "papers": merged_candidates,
            "elapsed_seconds": total_elapsed,
            "used_fallback": used_fallback,
            "primary_provider": preferred_provider,
            "providers_used": merged_providers,
            "source_stats": merged_stats,
            "query_variants": query_variants,
        }

    def _build_domain_authority_queries_with_llm(self, query: str) -> list[str]:
        safe_query = re.sub(r"\s+", " ", str(query or "").strip())
        if not safe_query or not is_configured():
            return []

        prompt = (
            "You are a research retrieval planner.\n"
            "Given a research domain, output concise English search queries that prioritize:\n"
            "1) seminal/most representative papers,\n"
            "2) highly-cited papers,\n"
            "3) authoritative surveys/benchmarks.\n"
            "Avoid generic keyword-only variants.\n"
            "Return JSON only: {\"queries\": [\"...\"]}\n\n"
            f"Domain: {safe_query}"
        )
        try:
            response = chat(
                [{"role": "user", "content": prompt}],
                max_tokens=260,
                timeout=25,
            )
            content = str(response.choices[0].message.content or "").strip()
            payload = self._extract_json_payload(content)
            if not isinstance(payload, dict):
                return []
            raw_queries = payload.get("queries") or []
            if not isinstance(raw_queries, list):
                return []
            normalized: list[str] = []
            seen: set[str] = set()
            for item in raw_queries:
                text = re.sub(r"\s+", " ", str(item or "").strip())
                if len(text) < 3:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(text)
                if len(normalized) >= 6:
                    break
            return normalized
        except Exception:  # noqa: BLE001
            logger.warning("domain authority query planning with llm failed", exc_info=True)
            return []

    def _build_domain_authority_queries(self, query: str) -> list[str]:
        safe_query = re.sub(r"\s+", " ", str(query or "").strip())
        if not safe_query:
            return []

        llm_candidates = self._build_domain_authority_queries_with_llm(safe_query)
        heuristic_candidates = [
            safe_query,
            f"{safe_query} seminal paper",
            f"{safe_query} survey review",
            f"{safe_query} benchmark",
            f"{safe_query} highly cited",
        ]
        candidates = [*llm_candidates, *heuristic_candidates]
        deduped: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            normalized = re.sub(r"\s+", " ", str(item or "").strip())
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped[:5]

    def _search_candidates_for_query(
        self,
        *,
        query: str,
        limit: int,
        allow_mock: bool,
        preferred_provider: str = "semantic_scholar",
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 60))
        primary_provider = self._normalize_search_provider(preferred_provider)
        secondary_provider = "semantic_scholar" if primary_provider == "openalex" else "openalex"
        provider_chain = [primary_provider, secondary_provider]
        provider_errors: dict[str, Exception] = {}

        for index, provider_name in enumerate(provider_chain):
            search_start = perf_counter()
            try:
                if provider_name == "openalex":
                    payload = self.openalex.search_papers(query=query, limit=safe_limit)
                else:
                    payload = self.semantic.search_papers(query=query, limit=safe_limit)
                papers = payload.get("papers", [])
                if papers:
                    used_fallback = index > 0
                    return {
                        "provider": provider_name,
                        "status": "fallback" if used_fallback else "done",
                        "papers": papers,
                        "elapsed_seconds": perf_counter() - search_start,
                        "used_fallback": used_fallback,
                        "primary_provider": primary_provider,
                    }
            except (SemanticScholarClientError, OpenAlexClientError) as exc:
                provider_errors[provider_name] = exc

        if provider_errors:
            logger.warning(
                "query search failed on both providers: primary=%s, errors=%s",
                primary_provider,
                {key: str(value) for key, value in provider_errors.items()},
            )

        if allow_mock:
            return {
                "provider": "mock",
                "status": "fallback",
                "papers": self._fallback_papers(query=query, max_papers=safe_limit),
                "elapsed_seconds": 0.0,
                "used_fallback": True,
                "primary_provider": primary_provider,
            }

        return {
            "provider": primary_provider,
            "status": "fallback",
            "papers": [],
            "elapsed_seconds": 0.0,
            "used_fallback": False,
            "primary_provider": primary_provider,
        }

    def _normalize_search_provider(self, preferred_provider: str) -> str:
        normalized = str(preferred_provider or "semantic_scholar").strip().lower()
        if normalized.startswith("openalex"):
            return "openalex"
        return "semantic_scholar"

    def _normalize_seed_input_value(self, *, input_type: str, input_value: str) -> str:
        value = str(input_value or "").strip()
        if not value:
            return ""

        normalized_type = str(input_type or "").strip().lower()
        if normalized_type == "arxiv_id":
            normalized = re.sub(r"^arxiv:\s*", "", value, flags=re.IGNORECASE)
            normalized = re.sub(
                r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/",
                "",
                normalized,
                flags=re.IGNORECASE,
            )
            normalized = re.sub(r"\.pdf$", "", normalized, flags=re.IGNORECASE)
            normalized = re.sub(r"\s+", "", normalized).strip().strip("/")
            return normalized

        if normalized_type == "doi":
            normalized = re.sub(r"^doi:\s*", "", value, flags=re.IGNORECASE)
            normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", normalized, flags=re.IGNORECASE)
            normalized = re.sub(r"\s+", "", normalized).strip()
            return normalized

        return value

    def _seed_search_trace(
        self,
        *,
        input_type: str,
        input_value: str,
        preferred_provider: str = "semantic_scholar",
    ) -> tuple[str, list[str]]:
        safe_value = self._normalize_seed_input_value(input_type=input_type, input_value=input_value)
        normalized_provider = str(preferred_provider or "semantic_scholar").strip().lower()
        use_openalex = normalized_provider == "openalex"
        if input_type == "arxiv_id":
            return (
                (
                    "正在解析 arXiv ID，并行定位种子论文及其关联研究。"
                ),
                [f"https://api.openalex.org/works/arXiv:{quote_plus(safe_value)}"]
                if use_openalex
                else [f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{quote_plus(safe_value)}"],
            )
        if input_type == "doi":
            return (
                (
                    "正在解析 DOI，并行定位种子论文及其关联研究。"
                ),
                [f"https://api.openalex.org/works?search={quote_plus(safe_value)}"]
                if use_openalex
                else [f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote_plus(safe_value)}"],
            )
        return (
            "正在根据论文标题检索种子论文并拉取引用/被引关系。",
            [
                f"https://api.semanticscholar.org/graph/v1/paper/search?query={quote_plus(safe_value)}",
                f"https://api.openalex.org/works?search={quote_plus(safe_value)}",
            ],
        )

    def _collect_seed_candidates(self, seed_paper: dict[str, Any], candidate_limit: int) -> list[dict[str, Any]]:
        normalized_seed = self._normalize_seed_candidate(seed_paper, relation_type="seed")
        if not normalized_seed:
            return []

        references = seed_paper.get("references") or []
        citations = seed_paper.get("citations") or []
        normalized_seed["reference_ids"] = [
            str(item.get("paper_id") or "").strip()
            for item in references
            if isinstance(item, dict) and str(item.get("paper_id") or "").strip()
        ][:120]
        normalized_seed["citation_ids"] = [
            str(item.get("paper_id") or "").strip()
            for item in citations
            if isinstance(item, dict) and str(item.get("paper_id") or "").strip()
        ][:120]

        candidates = [normalized_seed]
        for item in citations:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_seed_candidate(item, relation_type="citation")
            if normalized:
                candidates.append(normalized)
        for item in references:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_seed_candidate(item, relation_type="reference")
            if normalized:
                candidates.append(normalized)

        return self._merge_candidate_lists(primary=[], secondary=candidates, limit=candidate_limit)

    def _normalize_seed_candidate(
        self,
        payload: dict[str, Any],
        *,
        relation_type: str = "",
    ) -> dict[str, Any] | None:
        paper_id = str(payload.get("paper_id") or "").strip()
        title = str(payload.get("title") or "").strip()
        if not paper_id or not title:
            return None

        publication_date = str(payload.get("publication_date") or "").strip()
        month = self._safe_int(payload.get("month"))
        if month <= 0:
            month = self._month_from_publication_date(publication_date)

        return {
            "paper_id": paper_id,
            "title": title,
            "abstract": self._normalize_abstract_text(payload.get("abstract")),
            "year": self._safe_int(payload.get("year")) or None,
            "month": month if 1 <= month <= 12 else None,
            "publication_date": publication_date,
            "citation_count": self._safe_int(payload.get("citation_count")),
            "venue": str(payload.get("venue") or "Unknown Venue").strip() or "Unknown Venue",
            "fields_of_study": [
                str(item).strip()
                for item in (payload.get("fields_of_study") or [])
                if str(item).strip()
            ][:5],
            "authors": [
                str(item).strip()
                for item in (payload.get("authors") or [])
                if str(item).strip()
            ][:8],
            "url": payload.get("url"),
            "reference_ids": [
                str(item).strip()
                for item in (payload.get("reference_ids") or [])
                if str(item).strip()
            ][:120],
            "citation_ids": [
                str(item).strip()
                for item in (payload.get("citation_ids") or [])
                if str(item).strip()
            ][:120],
            "seed_relation": relation_type.strip().lower(),
        }

    def _merge_candidate_lists(
        self,
        *,
        primary: list[dict[str, Any]],
        secondary: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_titles: set[str] = set()
        for payload in [*primary, *secondary]:
            normalized = self._normalize_retrieved_paper(payload)
            paper_id = str(normalized.get("paper_id") or "").strip().lower()
            title = str(normalized.get("title") or "").strip()
            if not paper_id or not title:
                continue
            title_key = re.sub(r"\s+", " ", title.lower()).strip()
            if paper_id in seen_ids or title_key in seen_titles:
                continue
            seen_ids.add(paper_id)
            seen_titles.add(title_key)
            merged.append(normalized)
            if len(merged) >= max(1, limit):
                break
        return merged

    def _resolve_seed_candidate_by_title(
        self,
        *,
        input_title: str,
        candidates: list[dict[str, Any]],
        fallback_seed: dict[str, Any],
    ) -> dict[str, Any]:
        input_key = self._normalized_title_key(input_title)
        fallback = self._normalize_retrieved_paper(fallback_seed)
        best = fallback
        best_key: tuple[float, float, int, int] | None = None

        for item in candidates:
            normalized = self._normalize_retrieved_paper(item)
            title = str(normalized.get("title") or "").strip()
            paper_id = str(normalized.get("paper_id") or "").strip()
            if not title or not paper_id:
                continue
            candidate_key = self._normalized_title_key(title)
            exact = 1.0 if input_key and input_key == candidate_key else 0.0
            overlap = self._title_token_overlap(input_title, title)
            if exact <= 0 and overlap < 0.7:
                continue
            year = self._safe_int(normalized.get("year"))
            citation = self._safe_int(normalized.get("citation_count"))
            ranking_key = (
                exact,
                overlap,
                -year if year > 0 else -9999,
                min(citation, 200000),
            )
            if best_key is None or ranking_key > best_key:
                best_key = ranking_key
                best = normalized

        return best

    def _ensure_seed_first(self, papers: list[dict[str, Any]], seed_paper_id: str) -> list[dict[str, Any]]:
        seed_key = self._paper_key(seed_paper_id)
        if not seed_key:
            return papers
        for index, item in enumerate(papers):
            item_key = self._paper_key(str(item.get("paper_id") or ""))
            if item_key != seed_key:
                continue
            if index > 0:
                papers.insert(0, papers.pop(index))
            break
        return papers

    def _infer_seed_provider(self, seed_paper: dict[str, Any]) -> str:
        paper_id = self._paper_key(str(seed_paper.get("paper_id") or ""))
        if not paper_id:
            return "mock"
        if paper_id.startswith("openalex:"):
            return "openalex"
        if paper_id.startswith("arxiv:"):
            return "arxiv"
        if paper_id.startswith(("doi:", "title:", "pdf:")):
            return "mock"
        return "semantic_scholar"

    def _build_domain_expansion_plan(
        self,
        *,
        seed_paper: dict[str, Any],
        raw_query: str,
    ) -> dict[str, Any]:
        seed_title = str(seed_paper.get("title") or "").strip() or raw_query.strip()
        seed_abstract = self._normalize_abstract_text(seed_paper.get("abstract"))
        related_titles = self._collect_related_titles(seed_paper, limit=20)
        fallback = self._fallback_domain_expansion_plan(
            seed_title=seed_title,
            seed_abstract=seed_abstract,
            related_titles=related_titles,
        )

        if not is_configured():
            return fallback

        related_lines = "\n".join(f"- {item}" for item in related_titles[:10])
        related_hint = f"\nRelated paper titles:\n{related_lines}" if related_lines else ""

        prompt = (
            "You are an expert research mapper.\n"
            "Given one seed paper, infer its core research domain (not the paper title), "
            "and produce domain-oriented expansion queries.\n"
            "Return STRICT JSON only with this schema:\n"
            "{\n"
            '  "core_topic": "short english phrase",\n'
            '  "expansion_queries": ["query1", "query2", "..."]\n'
            "}\n"
            "Rules:\n"
            "1) Focus on the core domain and technical branches.\n"
            "2) Include method variants and cross-domain applications.\n"
            "3) Do NOT use near-duplicate title search strings.\n"
            "4) Queries must be concise English academic search phrases.\n"
            "5) 6-10 queries.\n\n"
            f"Seed title: {seed_title}\n"
            f"Seed abstract: {seed_abstract[:1500]}"
            f"{related_hint}"
        )
        try:
            response = chat(
                [{"role": "user", "content": prompt}],
                max_tokens=420,
                timeout=40,
            )
            raw_content = str(response.choices[0].message.content or "").strip()
            payload = self._extract_json_payload(raw_content)
            if not isinstance(payload, dict):
                return fallback

            core_topic = str(payload.get("core_topic") or "").strip()
            if not core_topic:
                core_topic = str(fallback.get("core_topic") or seed_title).strip()
            core_topic = self._canonicalize_core_topic(core_topic)
            seed_title_lower = seed_title.lower()
            seed_abstract_lower = seed_abstract.lower()
            if "attention is all you need" in seed_title_lower:
                core_topic = "transformer"
            elif "transformer" in seed_abstract_lower and "attention" in core_topic.lower():
                core_topic = "transformer"
            if self._title_token_overlap(core_topic, seed_title) >= 0.72:
                core_topic = str(fallback.get("core_topic") or "machine learning").strip() or "machine learning"
            expansion_queries = self._normalize_expansion_queries(
                [
                    *(payload.get("expansion_queries") or []),
                    *self._default_expansion_queries(core_topic),
                ],
                core_topic=core_topic,
                seed_title=seed_title,
            )
            if not expansion_queries:
                expansion_queries = list(fallback.get("queries") or [])
            return {
                "core_topic": core_topic,
                "queries": expansion_queries[:8],
                "used_llm": True,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("domain expansion with llm failed, fallback to heuristic expansion: %s", exc)
            return fallback

    def _fallback_domain_expansion_plan(
        self,
        *,
        seed_title: str,
        seed_abstract: str,
        related_titles: list[str],
    ) -> dict[str, Any]:
        core_topic = self._infer_core_topic(
            seed_title=seed_title,
            seed_abstract=seed_abstract,
            related_titles=related_titles,
        )
        queries = self._default_expansion_queries(core_topic)
        normalized_queries = self._normalize_expansion_queries(
            queries,
            core_topic=core_topic,
            seed_title=seed_title,
        )
        return {
            "core_topic": core_topic,
            "queries": normalized_queries[:8],
            "used_llm": False,
        }

    def _infer_core_topic(
        self,
        *,
        seed_title: str,
        seed_abstract: str,
        related_titles: list[str],
    ) -> str:
        related_corpus = " ".join(related_titles[:30])
        content = f"{seed_title}. {seed_abstract}. {related_corpus}".lower()
        topic_rules = [
            ("attention is all you need", "transformer"),
            ("self attention", "transformer"),
            ("multi head attention", "transformer"),
            ("transformer", "transformer"),
            ("vision transformer", "vision transformer"),
            ("swin transformer", "vision transformer"),
            ("bert", "transformer language model"),
            ("gpt", "large language model"),
            ("roformer", "transformer"),
            ("graph neural network", "graph neural network"),
            ("gnn", "graph neural network"),
            ("diffusion", "diffusion model"),
            ("reinforcement learning", "reinforcement learning"),
            ("multimodal", "multimodal learning"),
            ("retrieval augmented generation", "retrieval augmented generation"),
            ("rag", "retrieval augmented generation"),
            ("large language model", "large language model"),
            ("llm", "large language model"),
            ("vision language", "vision-language model"),
        ]
        for needle, topic in topic_rules:
            if needle in content:
                return topic

        alias_map = {
            "transformer": "transformer",
            "attention": "transformer",
            "swin": "vision transformer",
            "vit": "vision transformer",
            "bert": "transformer language model",
            "gpt": "large language model",
            "llm": "large language model",
            "graph": "graph neural network",
            "gnn": "graph neural network",
            "diffusion": "diffusion model",
            "retrieval": "retrieval augmented generation",
            "multimodal": "multimodal learning",
            "vision": "computer vision",
            "language": "natural language processing",
            "reinforcement": "reinforcement learning",
        }
        banned = {
            *self._STOPWORDS,
            "all",
            "you",
            "need",
            "is",
            "on",
            "via",
            "toward",
            "towards",
        }
        text_for_tokens = f"{seed_abstract} {related_corpus}".lower()
        token_counter: Counter[str] = Counter()
        for token in re.findall(r"[a-z0-9]{3,}", text_for_tokens):
            if token in banned:
                continue
            token_counter[token] += 1

        for token, _count in token_counter.most_common(20):
            if token in alias_map:
                return alias_map[token]

        if related_titles:
            return "machine learning"
        return "computer science"

    @staticmethod
    def _canonicalize_core_topic(core_topic: str) -> str:
        topic = str(core_topic or "").strip()
        lowered = topic.lower()
        if "transformer" in lowered:
            return "transformer"
        if "graph neural" in lowered or re.search(r"\bgnn\b", lowered):
            return "graph neural network"
        if "diffusion" in lowered:
            return "diffusion model"
        if "retrieval augmented generation" in lowered or re.search(r"\brag\b", lowered):
            return "retrieval augmented generation"
        if "multimodal" in lowered:
            return "multimodal learning"
        if "reinforcement learning" in lowered:
            return "reinforcement learning"
        if "large language model" in lowered or re.search(r"\bllm\b", lowered):
            return "large language model"
        if "vision transformer" in lowered:
            return "vision transformer"
        return topic or "machine learning"

    @staticmethod
    def _default_expansion_queries(core_topic: str) -> list[str]:
        topic = str(core_topic or "").strip() or "machine learning"
        lowered = topic.lower()
        if lowered == "transformer":
            return [
                "transformer",
                "transformer language model",
                "BERT pretraining transformer",
                "GPT transformer language model",
                "encoder decoder transformer sequence to sequence",
                "vision transformer",
                "long sequence transformer efficient attention",
                "transformer scaling laws",
            ]
        return [
            topic,
            f"{topic} variants",
            f"{topic} architecture",
            f"{topic} efficiency",
            f"{topic} benchmark",
            f"{topic} computer vision",
            f"{topic} multimodal",
            f"{topic} domain adaptation",
        ]

    @staticmethod
    def _collect_related_titles(seed_paper: dict[str, Any], limit: int = 20) -> list[str]:
        titles: list[str] = []
        for relation_key in ("references", "citations"):
            for item in seed_paper.get(relation_key) or []:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if title:
                    titles.append(title)
                if len(titles) >= max(1, limit):
                    return titles
        return titles

    def _normalize_expansion_queries(
        self,
        raw_queries: Any,
        *,
        core_topic: str,
        seed_title: str,
    ) -> list[str]:
        candidates: list[str] = []
        if isinstance(raw_queries, list):
            for item in raw_queries:
                text = str(item).strip()
                if text:
                    candidates.append(text)

        if core_topic.strip():
            candidates = [core_topic.strip(), *candidates]

        seed_key = self._normalized_title_key(seed_title)
        deduped: list[str] = []
        seen: set[str] = set()
        for query in candidates:
            normalized = re.sub(r"\s+", " ", query).strip()
            if len(normalized) < 3:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            # Avoid using near-duplicate full title as expansion query.
            if seed_key and self._normalized_title_key(normalized) == seed_key:
                continue
            if self._title_token_overlap(normalized, seed_title) >= 0.78:
                continue
            seen.add(key)
            deduped.append(normalized)
            if len(deduped) >= 10:
                break
        return deduped

    @staticmethod
    def _extract_json_payload(raw_content: str) -> dict[str, Any] | None:
        content = str(raw_content or "").strip()
        if not content:
            return None

        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL).strip()

        try:
            payload = json.loads(content)
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _normalized_title_key(text: str) -> str:
        lowered = str(text or "").lower()
        lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    @staticmethod
    def _title_token_overlap(left: str, right: str) -> float:
        left_tokens = {item for item in re.findall(r"[a-z0-9\u4e00-\u9fff]+", left.lower()) if len(item) >= 2}
        right_tokens = {item for item in re.findall(r"[a-z0-9\u4e00-\u9fff]+", right.lower()) if len(item) >= 2}
        if not left_tokens or not right_tokens:
            return 0.0
        intersection_size = len(left_tokens.intersection(right_tokens))
        union_size = len(left_tokens.union(right_tokens))
        if union_size <= 0:
            return 0.0
        return intersection_size / union_size

    @staticmethod
    def _merge_provider_labels(providers: set[str]) -> str:
        normalized: set[str] = set()
        for item in providers:
            text = str(item).strip()
            if not text:
                continue
            parts = [part.strip() for part in text.split("+") if part.strip()]
            normalized.update(parts or [text])
        if "semantic_scholar" in normalized:
            return "semantic_scholar"
        if "openalex" in normalized:
            return "openalex"
        if "arxiv" in normalized:
            return "arxiv"
        return "mock"

    @staticmethod
    def _month_from_publication_date(publication_date: str) -> int:
        text = str(publication_date or "").strip()
        if not text:
            return 0
        parts = text.split("-")
        if len(parts) < 2:
            return 0
        try:
            month = int(parts[1])
        except (TypeError, ValueError):
            return 0
        return month if 1 <= month <= 12 else 0

    @staticmethod
    def _normalize_paper_range_years(raw_value: int | None) -> int | None:
        if raw_value is None:
            return None
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return min(30, parsed)

    def _apply_paper_year_range(
        self,
        papers: list[dict[str, Any]],
        *,
        paper_range_years: int | None,
        preserve_paper_id: str = "",
    ) -> tuple[list[dict[str, Any]], dict[str, int | str | None]]:
        normalized_range = self._normalize_paper_range_years(paper_range_years)
        if normalized_range is None:
            return papers, {"applied": False, "removed": 0, "from_year": None}

        current_year = datetime.now(timezone.utc).year
        from_year = max(1, current_year - normalized_range)
        preserve_key = self._paper_key(preserve_paper_id)
        filtered: list[dict[str, Any]] = []
        removed = 0

        for paper in papers:
            normalized = self._normalize_retrieved_paper(paper)
            paper_key = self._paper_key(str(normalized.get("paper_id") or ""))
            year = self._safe_int(normalized.get("year"))
            in_range = year > 0 and year >= from_year
            if in_range or (preserve_key and paper_key == preserve_key):
                filtered.append(normalized)
            else:
                removed += 1

        return filtered, {"applied": True, "removed": removed, "from_year": from_year}

    @staticmethod
    def _build_year_range_hint(
        paper_range_years: int | None,
        stats: dict[str, int | str | None],
    ) -> str:
        normalized_range = GraphRAGService._normalize_paper_range_years(paper_range_years)
        if normalized_range is None:
            return ""
        from_year = int(stats.get("from_year") or 0)
        removed = int(stats.get("removed") or 0)
        if removed > 0:
            return f" 已应用近 {normalized_range} 年范围（{from_year} 年起），过滤 {removed} 条候选。"
        return f" 已应用近 {normalized_range} 年范围（{from_year} 年起）。"

    @staticmethod
    def _seed_relation_signal(seed_relation: str) -> float:
        relation = str(seed_relation or "").strip().lower()
        if relation == "seed":
            return 1.0
        if relation == "citation":
            return 0.96
        if relation == "reference":
            return 0.42
        return 0.0

    def _filter_and_rank_papers(
        self,
        papers: list[dict[str, Any]],
        max_papers: int,
        query: str,
        ranking_profile: str = "balanced",
        paper_range_years: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int | float]]:
        start = perf_counter()
        ranked: list[tuple[float, float, dict[str, Any]]] = []
        seen_ids: set[str] = set()
        seen_titles: set[str] = set()
        input_count = len(papers)
        current_year = datetime.now(timezone.utc).year

        profile = str(ranking_profile or "balanced").strip().lower()
        if profile == "seed_lineage":
            relevance_weight = 0.20
            citation_weight = 0.42
            recency_weight = 0.12
            relation_weight = 0.26
            representative_weight = 0.0
        elif profile == "domain_authority":
            relevance_weight = 0.18
            citation_weight = 0.52
            recency_weight = 0.08
            relation_weight = 0.0
            representative_weight = 0.22
        else:
            relevance_weight = 0.62
            citation_weight = 0.26
            recency_weight = 0.12
            relation_weight = 0.0
            representative_weight = 0.0

        for paper in papers:
            normalized = self._normalize_retrieved_paper(paper)
            paper_id = normalized["paper_id"].strip().lower()
            title = normalized["title"].strip()
            if not paper_id or not title:
                continue

            title_key = re.sub(r"\s+", " ", title.lower()).strip()
            if paper_id in seen_ids or title_key in seen_titles:
                continue
            seen_ids.add(paper_id)
            seen_titles.add(title_key)

            relevance = self._compute_relevance(
                query=query,
                title=normalized["title"],
                abstract=normalized["abstract"],
            )
            citation_count = self._safe_int(normalized["citation_count"])
            citation_signal = min(1.0, math.log1p(citation_count) / 8.0)
            year = self._safe_int(normalized["year"])
            age = max(0, current_year - year) if year > 0 else 12
            recency_signal = max(0.0, 1.0 - min(age, 12) / 12)
            relation_signal = self._seed_relation_signal(str(normalized.get("seed_relation") or ""))
            representative_signal = self._domain_representative_signal(normalized)
            score = (
                relevance * relevance_weight
                + citation_signal * citation_weight
                + recency_signal * recency_weight
                + relation_signal * relation_weight
                + representative_signal * representative_weight
            )

            ranked.append((score, representative_signal, normalized))

        ranked.sort(
            key=lambda item: (
                item[0],
                self._safe_int(item[2].get("citation_count")),
                item[1],
                self._safe_int(item[2].get("year")),
            ),
            reverse=True,
        )
        if profile == "domain_authority":
            selected = self._select_ranked_with_year_coverage(
                ranked=ranked,
                max_papers=max_papers,
                paper_range_years=paper_range_years,
            )
        else:
            selected = [item for _score, _representative, item in ranked[:max_papers]]
        stats = {
            "input": input_count,
            "deduped": len(ranked),
            "selected": len(selected),
            "elapsed_seconds": perf_counter() - start,
        }
        return selected, stats

    def _select_ranked_with_year_coverage(
        self,
        *,
        ranked: list[tuple[float, float, dict[str, Any]]],
        max_papers: int,
        paper_range_years: int | None,
    ) -> list[dict[str, Any]]:
        if max_papers <= 0:
            return []
        normalized_range = self._normalize_paper_range_years(paper_range_years)
        if normalized_range is None or normalized_range <= 1:
            return [item for _score, _representative, item in ranked[:max_papers]]

        current_year = datetime.now(timezone.utc).year
        target_years = list(range(max(1, current_year - normalized_range), current_year + 1))
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()

        for year in target_years:
            for _score, _representative, paper in ranked:
                paper_year = self._safe_int(paper.get("year"))
                paper_id = self._paper_key(str(paper.get("paper_id") or ""))
                if paper_year != year or not paper_id or paper_id in selected_ids:
                    continue
                selected.append(paper)
                selected_ids.add(paper_id)
                break

        if len(selected) >= max_papers:
            return selected[:max_papers]

        for _score, _representative, paper in ranked:
            paper_id = self._paper_key(str(paper.get("paper_id") or ""))
            if not paper_id or paper_id in selected_ids:
                continue
            selected.append(paper)
            selected_ids.add(paper_id)
            if len(selected) >= max_papers:
                break
        return selected

    @staticmethod
    def _domain_representative_signal(paper: dict[str, Any]) -> float:
        title = str(paper.get("title") or "").strip().lower()
        venue = str(paper.get("venue") or "").strip().lower()
        citation_count = GraphRAGService._safe_int(paper.get("citation_count"))

        citation_signal = min(1.0, math.log1p(citation_count) / 9.0)
        title_bonus = 0.0
        if any(
            token in title
            for token in (
                "survey",
                "systematic review",
                "review",
                "overview",
                "benchmark",
                "tutorial",
                "foundation",
                "foundations",
                "taxonomy",
            )
        ):
            title_bonus = 0.22
        elif any(token in title for token in ("analysis", "comparison", "empirical study", "best practices")):
            title_bonus = 0.1

        venue_bonus = 0.0
        if any(
            token in venue
            for token in (
                "nature",
                "science",
                "neurips",
                "nips",
                "icml",
                "iclr",
                "cvpr",
                "aaai",
                "acl",
                "kdd",
                "jmlr",
                "tpami",
            )
        ):
            venue_bonus = 0.12

        return min(1.0, citation_signal * 0.72 + title_bonus + venue_bonus)

    def _normalize_retrieved_paper(self, paper: dict[str, Any]) -> dict[str, Any]:
        fields = []
        for field in paper.get("fields_of_study") or []:
            value = str(field).strip()
            if value:
                fields.append(value)

        authors = []
        for author in paper.get("authors") or []:
            value = str(author).strip()
            if value:
                authors.append(value)

        year = self._safe_int(paper.get("year"))
        month = self._safe_int(paper.get("month"))
        url_value = str(paper.get("url") or "").strip()
        reference_ids = [
            str(item).strip()
            for item in (paper.get("reference_ids") or [])
            if str(item).strip()
        ]
        citation_ids = [
            str(item).strip()
            for item in (paper.get("citation_ids") or [])
            if str(item).strip()
        ]
        return {
            "paper_id": str(paper.get("paper_id") or "").strip(),
            "title": str(paper.get("title") or "").strip(),
            "abstract": self._normalize_abstract_text(paper.get("abstract")),
            "year": year if year > 0 else None,
            "month": month if 1 <= month <= 12 else None,
            "publication_date": str(paper.get("publication_date") or "").strip(),
            "citation_count": self._safe_int(paper.get("citation_count")),
            "venue": str(paper.get("venue") or "Unknown Venue").strip() or "Unknown Venue",
            "fields_of_study": list(dict.fromkeys(fields[:5])),
            "authors": authors[:8],
            "url": url_value or None,
            "reference_ids": list(dict.fromkeys(reference_ids[:120])),
            "citation_ids": list(dict.fromkeys(citation_ids[:120])),
            "seed_relation": str(paper.get("seed_relation") or "").strip().lower(),
        }

    @staticmethod
    def _build_retrieval_step(
        *,
        phase: str,
        title: str,
        detail: str,
        provider: str,
        count: int,
        links: list[str],
        elapsed_seconds: float,
        status: str = "done",
    ) -> dict[str, Any]:
        return {
            "phase": phase,
            "title": title,
            "detail": detail,
            "status": status,
            "provider": provider,
            "count": max(0, int(count)),
            "links": links,
            "elapsed_ms": max(0, int(elapsed_seconds * 1000)),
        }

    @staticmethod
    def _build_graph_trace_step(
        *,
        phase: str,
        title: str,
        detail: str,
        elapsed_seconds: float,
        status: str = "done",
    ) -> dict[str, Any]:
        return {
            "phase": phase,
            "title": title,
            "detail": detail,
            "status": status,
            "elapsed_ms": max(0, int(elapsed_seconds * 1000)),
        }

    def _fallback_papers(self, query: str, max_papers: int) -> list[dict[str, Any]]:
        base = query.strip() or "Research Topic"
        tokens = re.findall(r"[A-Za-z0-9]+", base)
        primary = " ".join(tokens[:4]) if tokens else base
        papers: list[dict[str, Any]] = []
        for idx in range(1, min(max_papers, 24) + 1):
            papers.append(
                {
                    "paper_id": f"fallback-{idx}",
                    "title": f"{primary} Study {idx}",
                    "abstract": (
                        f"This work studies {primary} from method, benchmark and system perspectives. "
                        f"It introduces practical evaluation protocol #{idx}."
                    ),
                    "year": 2020 + (idx % 6),
                    "month": (idx % 12) + 1,
                    "citation_count": max(0, 120 - idx * 7),
                    "venue": "Fallback Venue",
                    "fields_of_study": ["Computer Science"],
                    "authors": ["A. Researcher", "B. Engineer"],
                    "url": None,
                    "reference_ids": [],
                    "citation_ids": [],
                }
            )
        return papers

    def _build_graph_components(
        self,
        papers: list[dict[str, Any]],
        max_entities_per_paper: int,
        query: str,
    ) -> tuple[list[KnowledgeGraphNode], list[KnowledgeGraphNode], list[KnowledgeGraphNode], list[KnowledgeGraphEdge]]:
        normalized_papers: list[dict[str, Any]] = []
        for paper in papers:
            normalized = self._normalize_retrieved_paper(paper)
            paper_id = str(normalized.get("paper_id") or "").strip()
            title = str(normalized.get("title") or "").strip()
            if not paper_id or not title:
                continue
            normalized_papers.append(normalized)

        if not normalized_papers:
            return [], [], [], []

        # Try enriching citation relations so "引用关系得分" can be computed from real graph links.
        self._attach_relation_ids(normalized_papers)

        seed_paper = normalized_papers[0]
        seed_paper_id = str(seed_paper.get("paper_id") or "")
        seed_title = str(seed_paper.get("title") or "")
        seed_abstract = str(seed_paper.get("abstract") or "")

        citation_graph = self._build_citation_graph(normalized_papers)
        entity_counter: Counter[str] = Counter()
        entity_type_map: dict[str, str] = {}
        paper_entities: dict[str, set[str]] = defaultdict(set)
        paper_domains: dict[str, set[str]] = defaultdict(set)
        domain_counter: Counter[str] = Counter()
        domain_entities: dict[str, set[str]] = defaultdict(set)
        max_citation_count = max(
            1,
            max((self._safe_int(paper.get("citation_count")) for paper in normalized_papers), default=1),
        )

        paper_records: list[dict[str, Any]] = []

        for paper in normalized_papers:
            paper_id = str(paper.get("paper_id") or "")
            title = str(paper.get("title") or "").strip() or f"Paper {paper_id}"
            if not paper_id or not title:
                continue

            citation_count = self._safe_int(paper.get("citation_count"))
            influence = min(1.0, citation_count / max_citation_count)
            publication_month = self._extract_publication_month(paper)
            authors_text = self._format_authors(paper.get("authors") or [])
            abstract_text = self._normalize_abstract_text(paper.get("abstract"))
            keywords = self._extract_keywords(paper=paper)
            impact_factor, quartile = self._estimate_impact_metrics(citation_count, influence)
            size = 5.0 + min(16.0, math.log1p(citation_count + 1) * 2.2)

            extracted_entities = self._extract_entities(
                title=title,
                abstract=str(paper.get("abstract") or ""),
                max_entities=max_entities_per_paper,
            )
            concept_names: set[str] = set()
            for entity_name, entity_type, _score in extracted_entities:
                entity_counter[entity_name] += 1
                entity_type_map[entity_name] = entity_type
                paper_entities[paper_id].add(entity_name)
                concept_names.add(entity_name)

            domains = self._extract_domains(paper, query)
            for domain in domains:
                domain_counter[domain] += 1
                paper_domains[paper_id].add(domain)
                domain_entities[domain].update(paper_entities[paper_id])

            paper_records.append(
                {
                    "paper_id": paper_id,
                    "title": title,
                    "abstract": abstract_text,
                    "citation_count": citation_count,
                    "influence": influence,
                    "publication_month": publication_month,
                    "authors_text": authors_text,
                    "keywords": keywords,
                    "impact_factor": impact_factor,
                    "quartile": quartile,
                    "size": size,
                    "venue": str(paper.get("venue") or "Unknown Venue"),
                    "year": str(paper.get("year") or ""),
                    "url": str(paper.get("url") or ""),
                    "concepts": concept_names,
                }
            )

        seed_concepts = paper_entities.get(seed_paper_id, set())
        paper_nodes: list[KnowledgeGraphNode] = []
        for record in paper_records:
            paper_id = record["paper_id"]
            if paper_id == seed_paper_id:
                citation_score = 1.0
                semantic_score = 1.0
                concept_score = 1.0
                relevance = 1.0
            else:
                citation_score = self._citation_relation_score(seed_paper_id, paper_id, citation_graph)
                semantic_score = self._semantic_relevance_score(
                    seed_title=seed_title,
                    seed_abstract=seed_abstract,
                    paper_title=record["title"],
                    paper_abstract=record["abstract"],
                )
                concept_score = self._concept_overlap_score(seed_concepts, record["concepts"])
                relevance = max(0.0, min(1.0, citation_score * 0.5 + semantic_score * 0.3 + concept_score * 0.2))

            paper_nodes.append(
                KnowledgeGraphNode(
                    id=f"paper:{paper_id}",
                    paper_id=paper_id,
                    label=record["title"],
                    type="paper",
                    size=round(record["size"], 2),
                    score=round(min(1.0, record["citation_count"] / 500.0), 3),
                    meta={
                        "title": record["title"],
                        "year": record["year"],
                        "venue": record["venue"],
                        "url": record["url"],
                        "authors": record["authors_text"],
                        "abstract": record["abstract"],
                        "keywords": "|".join(record["keywords"]),
                        "published_month": str(record["publication_month"]),
                        "impact_factor": f"{record['impact_factor']:.1f}",
                        "quartile": record["quartile"],
                        "citation_count": str(record["citation_count"]),
                        "relevance": f"{relevance:.3f}",
                        "influence": f"{record['influence']:.3f}",
                        "citation_relation_score": f"{citation_score:.3f}",
                        "semantic_similarity_score": f"{semantic_score:.3f}",
                        "concept_overlap_score": f"{concept_score:.3f}",
                    },
                )
            )

        entity_nodes = self._build_entity_nodes(entity_counter, entity_type_map)
        domain_nodes = self._build_domain_nodes(domain_counter)
        edges = self._build_edges(
            paper_nodes=paper_nodes,
            entity_counter=entity_counter,
            paper_entities=paper_entities,
            paper_domains=paper_domains,
            domain_entities=domain_entities,
        )
        return paper_nodes, entity_nodes, domain_nodes, edges

    def _extract_entities(self, title: str, abstract: str, max_entities: int) -> list[tuple[str, str, float]]:
        text = f"{title}. {abstract}".strip()
        raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-\+]{2,}", text)
        token_counter: Counter[str] = Counter()

        for token in raw_tokens:
            normalized = token.lower()
            if normalized in self._STOPWORDS:
                continue
            if normalized.isdigit():
                continue
            token_counter[normalized] += 1

        acronym_hits = re.findall(r"\b[A-Z]{2,}\b", text)
        for acronym in acronym_hits:
            token_counter[acronym.lower()] += 2

        ranked = token_counter.most_common(max_entities * 2)
        entities: list[tuple[str, str, float]] = []
        seen: set[str] = set()
        for token, count in ranked:
            if token in seen:
                continue
            seen.add(token)
            label = token.upper() if token.isupper() else token.replace("-", " ").title()
            entity_type = self._infer_entity_type(token)
            score = min(1.0, 0.35 + count * 0.15)
            entities.append((label, entity_type, score))
            if len(entities) >= max_entities:
                break

        return entities

    @staticmethod
    def _infer_entity_type(token: str) -> str:
        lower = token.lower()
        if any(word in lower for word in ("dataset", "benchmark", "corpus")):
            return "dataset"
        if any(word in lower for word in ("model", "network", "transformer", "bert", "gpt", "gnn")):
            return "method"
        if any(word in lower for word in ("attack", "privacy", "security", "risk", "robust")):
            return "problem"
        if any(word in lower for word in ("system", "platform", "framework")):
            return "system"
        return "concept"

    @staticmethod
    def _extract_domains(paper: dict[str, Any], query: str) -> list[str]:
        raw_domains = [
            str(item).strip()
            for item in (paper.get("fields_of_study") or [])
            if str(item).strip()
        ]
        if raw_domains:
            return list(dict.fromkeys(raw_domains[:3]))

        query_lower = query.lower()
        if any(word in query_lower for word in ("biology", "protein", "gene", "medical")):
            return ["Biology", "Medicine"]
        if any(word in query_lower for word in ("crypto", "security", "encryption")):
            return ["Computer Science", "Mathematics"]
        return ["Computer Science"]

    def _attach_relation_ids(self, papers: list[dict[str, Any]]) -> None:
        for paper in papers:
            paper_id = str(paper.get("paper_id") or "").strip()
            if not paper_id:
                continue

            existing_references = {
                str(item).strip()
                for item in (paper.get("reference_ids") or [])
                if str(item).strip()
            }
            existing_citations = {
                str(item).strip()
                for item in (paper.get("citation_ids") or [])
                if str(item).strip()
            }

            relation_ids = self._fetch_relation_ids(paper_id)
            merged_references = list(dict.fromkeys([*existing_references, *relation_ids["references"]]))
            merged_citations = list(dict.fromkeys([*existing_citations, *relation_ids["citations"]]))

            paper["reference_ids"] = merged_references[:120]
            paper["citation_ids"] = merged_citations[:120]

    def _fetch_relation_ids(self, paper_id: str) -> dict[str, list[str]]:
        key = self._paper_key(paper_id)
        if key in self._paper_relation_cache:
            return self._paper_relation_cache[key]

        empty_result = {"references": [], "citations": []}
        if not key:
            return empty_result

        try:
            if key.startswith("openalex:"):
                payload = self.openalex.fetch_relation_ids(paper_id, limit=60)
            else:
                references = self.semantic.fetch_references(paper_id, limit=60)
                citations = self.semantic.fetch_citations(paper_id, limit=60)
                payload = {
                    "references": [
                        str(item.get("paper_id") or "").strip()
                        for item in references
                        if str(item.get("paper_id") or "").strip()
                    ],
                    "citations": [
                        str(item.get("paper_id") or "").strip()
                        for item in citations
                        if str(item.get("paper_id") or "").strip()
                    ],
                }
        except (SemanticScholarClientError, OpenAlexClientError, ValueError) as exc:
            logger.debug("relation enrichment failed for paper %s: %s", paper_id, exc)
            payload = empty_result
        except Exception as exc:  # noqa: BLE001
            logger.warning("unexpected relation enrichment error for paper %s: %s", paper_id, exc)
            payload = empty_result

        normalized = {
            "references": [
                str(item).strip()
                for item in (payload.get("references") or [])
                if str(item).strip()
            ],
            "citations": [
                str(item).strip()
                for item in (payload.get("citations") or [])
                if str(item).strip()
            ],
        }
        normalized["references"] = list(dict.fromkeys(normalized["references"]))
        normalized["citations"] = list(dict.fromkeys(normalized["citations"]))
        self._paper_relation_cache[key] = normalized
        return normalized

    def _build_citation_graph(self, papers: list[dict[str, Any]]) -> dict[str, set[str]]:
        id_by_key: dict[str, str] = {}
        for paper in papers:
            paper_id = str(paper.get("paper_id") or "").strip()
            key = self._paper_key(paper_id)
            if key:
                id_by_key[key] = paper_id

        adjacency: dict[str, set[str]] = {key: set() for key in id_by_key}
        for paper in papers:
            paper_id = str(paper.get("paper_id") or "").strip()
            paper_key = self._paper_key(paper_id)
            if not paper_key or paper_key not in adjacency:
                continue

            related_ids = [
                *(
                    str(item).strip()
                    for item in (paper.get("reference_ids") or [])
                    if str(item).strip()
                ),
                *(
                    str(item).strip()
                    for item in (paper.get("citation_ids") or [])
                    if str(item).strip()
                ),
            ]

            for related_id in related_ids:
                related_key = self._paper_key(related_id)
                if not related_key or related_key not in adjacency:
                    continue
                if related_key == paper_key:
                    continue
                adjacency[paper_key].add(related_key)
                adjacency[related_key].add(paper_key)

        return adjacency

    def _citation_relation_score(
        self,
        seed_paper_id: str,
        paper_id: str,
        citation_graph: dict[str, set[str]],
    ) -> float:
        seed_key = self._paper_key(seed_paper_id)
        paper_key = self._paper_key(paper_id)
        if not seed_key or not paper_key:
            return 0.0
        if seed_key == paper_key:
            return 1.0

        seed_neighbors = citation_graph.get(seed_key, set())
        paper_neighbors = citation_graph.get(paper_key, set())
        if paper_key in seed_neighbors or seed_key in paper_neighbors:
            return 1.0

        if seed_neighbors.intersection(paper_neighbors):
            return 0.5
        return 0.0

    @staticmethod
    def _concept_overlap_score(seed_concepts: set[str], paper_concepts: set[str]) -> float:
        if not seed_concepts and not paper_concepts:
            return 0.0
        if not seed_concepts or not paper_concepts:
            return 0.0
        union_size = len(seed_concepts.union(paper_concepts))
        if union_size <= 0:
            return 0.0
        shared = len(seed_concepts.intersection(paper_concepts))
        return max(0.0, min(1.0, shared / union_size))

    def _semantic_relevance_score(
        self,
        *,
        seed_title: str,
        seed_abstract: str,
        paper_title: str,
        paper_abstract: str,
    ) -> float:
        seed_text = self._normalize_abstract_text(f"{seed_title}. {seed_abstract}")
        paper_text = self._normalize_abstract_text(f"{paper_title}. {paper_abstract}")
        if not seed_text or not paper_text:
            return 0.0

        vector_a = self._get_embedding(seed_text)
        vector_b = self._get_embedding(paper_text)
        if vector_a and vector_b:
            cosine = self._cosine_similarity(vector_a, vector_b)
            return max(0.0, min(1.0, (cosine + 1.0) / 2.0))

        return self._fallback_semantic_similarity(seed_text, paper_text)

    def _get_embedding_client(self):
        if self._embedding_unavailable:
            return None
        if self._embedding_client is not None:
            return self._embedding_client
        if not is_configured():
            self._embedding_unavailable = True
            return None
        try:
            self._embedding_client = get_client()
            return self._embedding_client
        except Exception as exc:  # noqa: BLE001
            logger.warning("embedding client unavailable, fallback to lexical similarity: %s", exc)
            self._embedding_unavailable = True
            return None

    def _get_embedding(self, text: str) -> list[float]:
        clean_text = self._normalize_abstract_text(text)[:2000]
        if not clean_text:
            return []

        cache_key = clean_text
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        client = self._get_embedding_client()
        if client is None:
            return []

        try:
            response = client.embeddings.create(
                model=self.settings.embedding_model,
                input=clean_text,
            )
            vector = list(response.data[0].embedding or []) if response.data else []
            if vector:
                self._embedding_cache[cache_key] = vector
            return vector
        except Exception as exc:  # noqa: BLE001
            logger.warning("embedding request failed, fallback to lexical similarity: %s", exc)
            self._embedding_unavailable = True
            return []

    @staticmethod
    def _cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
        if not vector_a or not vector_b or len(vector_a) != len(vector_b):
            return 0.0
        dot = sum(left * right for left, right in zip(vector_a, vector_b))
        norm_a = math.sqrt(sum(item * item for item in vector_a))
        norm_b = math.sqrt(sum(item * item for item in vector_b))
        denom = norm_a * norm_b
        if denom <= 0:
            return 0.0
        return dot / denom

    def _fallback_semantic_similarity(self, left_text: str, right_text: str) -> float:
        left_tokens = set(self._semantic_tokens(left_text))
        right_tokens = set(self._semantic_tokens(right_text))
        if not left_tokens or not right_tokens:
            return 0.0
        shared = len(left_tokens.intersection(right_tokens))
        union = len(left_tokens.union(right_tokens))
        if union <= 0:
            return 0.0
        return max(0.0, min(1.0, shared / union))

    def _semantic_tokens(self, text: str) -> list[str]:
        lowered = (text or "").lower()
        latin_tokens = re.findall(r"[a-z0-9]{2,}", lowered)
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", text or "")
        cjk_bigrams = [f"{cjk_chars[index]}{cjk_chars[index + 1]}" for index in range(len(cjk_chars) - 1)]
        merged = [*latin_tokens, *cjk_bigrams]
        return [token for token in merged if token and token not in self._STOPWORDS]

    @staticmethod
    def _paper_key(paper_id: str) -> str:
        return str(paper_id or "").strip().lower()

    def _compute_relevance(self, query: str, title: str, abstract: str) -> float:
        query_tokens = set(self._relevance_tokens(query))
        if not query_tokens:
            return 0.0

        title_tokens = set(self._relevance_tokens(title))
        doc_tokens = set(self._relevance_tokens(f"{title} {abstract}"))

        if not doc_tokens:
            return 0.0

        title_overlap = len(query_tokens.intersection(title_tokens))
        doc_overlap = len(query_tokens.intersection(doc_tokens))

        title_ratio = title_overlap / len(query_tokens)
        doc_ratio = doc_overlap / len(query_tokens)

        return max(0.0, min(1.0, title_ratio * 0.7 + doc_ratio * 0.3))

    def _relevance_tokens(self, text: str) -> list[str]:
        return self._semantic_tokens(text)

    @staticmethod
    def _extract_publication_month(paper: dict[str, Any]) -> int:
        month = GraphRAGService._safe_int(paper.get("month"))
        if 1 <= month <= 12:
            return month
        publication_date = str(paper.get("publication_date") or "").strip()
        if publication_date:
            parts = publication_date.split("-")
            if len(parts) >= 2:
                parsed = GraphRAGService._safe_int(parts[1])
                if 1 <= parsed <= 12:
                    return parsed
        return 1

    @staticmethod
    def _format_authors(raw_authors: Any) -> str:
        authors: list[str] = []
        if isinstance(raw_authors, list):
            for item in raw_authors:
                text = str(item).strip()
                if text:
                    authors.append(text)
        if not authors:
            return "Unknown Authors"
        if len(authors) <= 3:
            return ", ".join(authors)
        return f"{', '.join(authors[:3])}, et al."

    @staticmethod
    def _normalize_abstract_text(raw_abstract: Any) -> str:
        text = str(raw_abstract or "").strip()
        if not text:
            return ""
        return re.sub(r"\s+", " ", text)

    def _extract_keywords(self, paper: dict[str, Any]) -> list[str]:
        fields = paper.get("fields_of_study") or []
        keywords: list[str] = []
        for field in fields:
            value = str(field).strip()
            if value:
                keywords.append(value)

        dedup: list[str] = []
        seen: set[str] = set()
        for item in keywords:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            dedup.append(item)
            if len(dedup) >= 5:
                break
        return dedup

    @staticmethod
    def _estimate_impact_metrics(citation_count: int, influence: float) -> tuple[float, str]:
        if citation_count >= 5000:
            return 15.8, "Q1"
        if citation_count >= 1200:
            return 12.4, "Q1"
        if citation_count >= 400:
            return 8.9, "Q2"
        if citation_count >= 150:
            return 5.6, "Q2"
        if citation_count >= 50:
            return 3.6, "Q3"
        # Use influence as a weak signal for low-citation papers.
        proxy = 1.8 + influence * 1.4
        return round(proxy, 1), "Q4"

    def _build_entity_nodes(
        self,
        entity_counter: Counter[str],
        entity_type_map: dict[str, str],
    ) -> list[KnowledgeGraphNode]:
        nodes: list[KnowledgeGraphNode] = []
        for name, frequency in entity_counter.most_common(60):
            size = 4.0 + min(12.0, frequency * 1.6)
            nodes.append(
                KnowledgeGraphNode(
                    id=f"entity:{self._slug(name)}",
                    label=name,
                    type="entity",
                    size=round(size, 2),
                    score=round(min(1.0, frequency / 8.0), 3),
                    meta={"entity_type": entity_type_map.get(name, "concept")},
                )
            )
        return nodes

    def _build_domain_nodes(self, domain_counter: Counter[str]) -> list[KnowledgeGraphNode]:
        nodes: list[KnowledgeGraphNode] = []
        for domain, frequency in domain_counter.most_common(12):
            nodes.append(
                KnowledgeGraphNode(
                    id=f"domain:{self._slug(domain)}",
                    label=domain,
                    type="domain",
                    size=6.0 + frequency * 1.8,
                    score=round(min(1.0, frequency / 12.0), 3),
                    meta={},
                )
            )
        return nodes

    def _build_edges(
        self,
        paper_nodes: list[KnowledgeGraphNode],
        entity_counter: Counter[str],
        paper_entities: dict[str, set[str]],
        paper_domains: dict[str, set[str]],
        domain_entities: dict[str, set[str]],
    ) -> list[KnowledgeGraphEdge]:
        edges: list[KnowledgeGraphEdge] = []

        for paper in paper_nodes:
            paper_id = paper.paper_id or ""
            for entity_name in sorted(paper_entities.get(paper_id, set())):
                weight = min(1.0, 0.25 + entity_counter.get(entity_name, 0) * 0.12)
                edges.append(
                    KnowledgeGraphEdge(
                        source=paper.id,
                        target=f"entity:{self._slug(entity_name)}",
                        relation="mentions",
                        weight=round(weight, 3),
                        meta={
                            "source_paper_id": paper_id,
                            "target_entity": entity_name,
                        },
                    )
                )

            for domain in sorted(paper_domains.get(paper_id, set())):
                edges.append(
                    KnowledgeGraphEdge(
                        source=paper.id,
                        target=f"domain:{self._slug(domain)}",
                        relation="belongs_to",
                        weight=0.8,
                        meta={
                            "source_paper_id": paper_id,
                            "target_domain": domain,
                        },
                    )
                )

        paper_index = {node.paper_id: node for node in paper_nodes if node.paper_id}
        related_edges: list[KnowledgeGraphEdge] = []
        for left_id, right_id in combinations(sorted(paper_index.keys()), 2):
            left_entities = paper_entities.get(left_id, set())
            right_entities = paper_entities.get(right_id, set())
            if not left_entities or not right_entities:
                continue
            shared = left_entities.intersection(right_entities)
            if not shared:
                continue
            denom = max(1, min(len(left_entities), len(right_entities)))
            weight = min(1.0, len(shared) / denom + 0.15)
            related_edges.append(
                KnowledgeGraphEdge(
                    source=paper_index[left_id].id,
                    target=paper_index[right_id].id,
                    relation="related",
                    weight=round(weight, 3),
                    meta={
                        "left_paper_id": left_id,
                        "right_paper_id": right_id,
                        "shared_entities": ",".join(sorted(shared)[:6]),
                    },
                )
            )

        edges.extend(sorted(related_edges, key=lambda item: item.weight, reverse=True)[:40])

        for domain, entities in sorted(domain_entities.items()):
            for entity_name in sorted(entities):
                edges.append(
                    KnowledgeGraphEdge(
                        source=f"domain:{self._slug(domain)}",
                        target=f"entity:{self._slug(entity_name)}",
                        relation="covers",
                        weight=round(min(1.0, 0.2 + entity_counter.get(entity_name, 0) * 0.1), 3),
                        meta={"domain": domain, "entity": entity_name},
                    )
                )

        return edges

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return max(0, int(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _slug(text: str) -> str:
        lowered = text.strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
        return slug or "node"

    @staticmethod
    def _build_summary(
        query: str,
        paper_count: int,
        entity_count: int,
        domain_count: int,
        edge_count: int,
        stored: bool,
    ) -> str:
        store_text = "已写入 Neo4j" if stored else "Neo4j 当前不可用，结果仅返回前端"
        return (
            f"围绕检索词“{query}”抓取 {paper_count} 篇论文，抽取 {entity_count} 个实体、"
            f"{domain_count} 个领域节点，构建 {edge_count} 条关系；{store_text}。"
        )


@lru_cache
def get_graphrag_service() -> GraphRAGService:
    return GraphRAGService()
