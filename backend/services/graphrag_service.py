from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from itertools import combinations
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
from core.llm_client import get_client, is_configured
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
        retrieval_payload = self._retrieve_papers_with_trace(request.query, request.max_papers)
        papers = [RetrievedPaper.model_validate(item) for item in retrieval_payload["selected_papers"]]
        steps = [RetrievalTraceStep.model_validate(item) for item in retrieval_payload["steps"]]
        return KnowledgeGraphRetrievalResponse(
            query=request.query,
            provider=str(retrieval_payload["provider"]),
            candidate_count=int(retrieval_payload["candidate_count"]),
            selected_count=len(papers),
            papers=papers,
            steps=steps,
            generated_at=datetime.now(timezone.utc),
        )

    def _retrieve_papers(self, query: str, max_papers: int) -> list[dict[str, Any]]:
        payload = self._retrieve_papers_with_trace(query=query, max_papers=max_papers)
        return payload["selected_papers"]

    def _retrieve_papers_with_trace(self, query: str, max_papers: int) -> dict[str, Any]:
        safe_query = query.strip()
        safe_max = max(1, max_papers)
        candidate_limit = min(60, max(safe_max + 6, safe_max * 3))
        steps: list[dict[str, Any]] = []
        web_links = [
            f"https://api.semanticscholar.org/graph/v1/paper/search?query={quote_plus(safe_query)}",
            f"https://api.openalex.org/works?search={quote_plus(safe_query)}",
        ]
        steps.append(
            self._build_retrieval_step(
                phase="search_web",
                title="LLM 检索规划与网页搜索",
                detail="已构造学术检索查询，并向 Semantic Scholar/OpenAlex 搜索接口发起请求。",
                provider="semantic_scholar+openalex",
                count=0,
                links=web_links,
                elapsed_seconds=0.0,
            )
        )

        if self.settings.graphrag_force_mock:
            candidates = self._fallback_papers(query=safe_query, max_papers=candidate_limit)
            steps.append(
                self._build_retrieval_step(
                    phase="retrieve",
                    title="候选论文检索",
                    detail=f"已启用 mock 模式，生成 {len(candidates)} 条候选论文。",
                    status="fallback",
                    provider="mock",
                    count=len(candidates),
                    links=[],
                    elapsed_seconds=0.0,
                )
            )
            selected_papers, filter_stats = self._filter_and_rank_papers(candidates, safe_max, safe_query)
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
                    elapsed_seconds=0.0,
                )
            )
            return {
                "provider": "mock",
                "candidate_count": len(candidates),
                "selected_papers": selected_papers,
                "steps": steps,
            }

        semantic_error: Exception | None = None
        provider_used = "semantic_scholar"
        candidate_papers: list[dict[str, Any]] = []

        semantic_start = perf_counter()
        try:
            payload = self.semantic.search_papers(query=safe_query, limit=candidate_limit)
            candidate_papers = payload.get("papers", [])
            if candidate_papers:
                steps.append(
                    self._build_retrieval_step(
                        phase="retrieve",
                        title="候选论文检索",
                        detail=f"Semantic Scholar 返回 {len(candidate_papers)} 条候选论文。",
                        provider="semantic_scholar",
                        count=len(candidate_papers),
                        links=[],
                        elapsed_seconds=perf_counter() - semantic_start,
                    )
                )
        except SemanticScholarClientError as exc:
            semantic_error = exc

        if not candidate_papers:
            openalex_start = perf_counter()
            try:
                openalex_payload = self.openalex.search_papers(query=safe_query, limit=candidate_limit)
                candidate_papers = openalex_payload.get("papers", [])
                if candidate_papers:
                    provider_used = "openalex"
                    steps.append(
                        self._build_retrieval_step(
                            phase="retrieve",
                            title="候选论文检索",
                            detail=f"Semantic Scholar 不可用，已切换 OpenAlex，返回 {len(candidate_papers)} 条候选论文。",
                            status="fallback",
                            provider="openalex",
                            count=len(candidate_papers),
                            links=[],
                            elapsed_seconds=perf_counter() - openalex_start,
                        )
                    )
            except OpenAlexClientError as exc:
                if semantic_error is not None:
                    logger.warning(
                        "Semantic Scholar and OpenAlex both failed: semantic=%s, openalex=%s",
                        semantic_error,
                        exc,
                    )
                else:
                    logger.warning("OpenAlex fallback search failed: %s", exc)

        if not candidate_papers:
            provider_used = "mock"
            candidate_papers = self._fallback_papers(query=safe_query, max_papers=candidate_limit)
            steps.append(
                self._build_retrieval_step(
                    phase="retrieve",
                    title="候选论文检索",
                    detail=f"外部检索失败，已降级为 mock 数据（{len(candidate_papers)} 条候选）。",
                    status="fallback",
                    provider="mock",
                    count=len(candidate_papers),
                    links=[],
                    elapsed_seconds=0.0,
                )
            )

        selected_papers, filter_stats = self._filter_and_rank_papers(candidate_papers, safe_max, safe_query)
        steps.append(
            self._build_retrieval_step(
                phase="filter",
                title="候选筛选与排序",
                detail=(
                    f"输入 {filter_stats['input']} 条，去重后 {filter_stats['deduped']} 条，"
                    f"按相关度/引用数/新近性筛选保留 {filter_stats['selected']} 条。"
                ),
                provider=provider_used,
                count=len(selected_papers),
                links=[],
                elapsed_seconds=filter_stats["elapsed_seconds"],
            )
        )
        return {
            "provider": provider_used,
            "candidate_count": len(candidate_papers),
            "selected_papers": selected_papers,
            "steps": steps,
        }

    def _filter_and_rank_papers(
        self,
        papers: list[dict[str, Any]],
        max_papers: int,
        query: str,
    ) -> tuple[list[dict[str, Any]], dict[str, int | float]]:
        start = perf_counter()
        ranked: list[tuple[float, dict[str, Any]]] = []
        seen_ids: set[str] = set()
        seen_titles: set[str] = set()
        input_count = len(papers)

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
            current_year = datetime.now(timezone.utc).year
            age = max(0, current_year - year) if year > 0 else 12
            recency_signal = max(0.0, 1.0 - min(age, 12) / 12)
            score = relevance * 0.72 + citation_signal * 0.18 + recency_signal * 0.10

            ranked.append((score, normalized))

        ranked.sort(
            key=lambda item: (
                item[0],
                self._safe_int(item[1].get("citation_count")),
                self._safe_int(item[1].get("year")),
            ),
            reverse=True,
        )
        selected = [item for _score, item in ranked[:max_papers]]
        stats = {
            "input": input_count,
            "deduped": len(ranked),
            "selected": len(selected),
            "elapsed_seconds": perf_counter() - start,
        }
        return selected, stats

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
            keywords = self._extract_keywords(
                paper=paper,
                title=title,
                abstract=abstract_text,
            )
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

    def _extract_keywords(self, paper: dict[str, Any], title: str, abstract: str) -> list[str]:
        fields = paper.get("fields_of_study") or []
        keywords: list[str] = []
        for field in fields:
            value = str(field).strip()
            if value:
                keywords.append(value)

        if not keywords:
            token_source = f"{title} {abstract}"
            tokens = [token for token in self._relevance_tokens(token_source) if len(token) >= 4]
            keywords = [token.title() for token in tokens]

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
