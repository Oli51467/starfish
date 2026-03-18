from __future__ import annotations

from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from functools import lru_cache
import logging
import math
import re
from time import perf_counter
from typing import Any

from core.settings import Settings, get_settings
from external.openalex import OpenAlexClient
from external.semantic_scholar import SemanticScholarClient
from services.retrieval.providers.arxiv_provider import ArxivProvider
from services.retrieval.providers.base import RetrievalProvider
from services.retrieval.providers.openalex_provider import OpenAlexProvider
from services.retrieval.providers.semantic_scholar_provider import SemanticScholarProvider

logger = logging.getLogger(__name__)


@dataclass
class _ProviderExecution:
    provider: str
    papers: list[dict[str, Any]]
    elapsed_seconds: float
    error: str = ""


class MultiSourceRetriever:
    """Parallel multi-source retriever with merge and ranking."""

    _DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        semantic_client: SemanticScholarClient | None = None,
        openalex_client: OpenAlexClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.max_workers = max(2, int(self.settings.retrieval_max_workers))
        self.provider_timeout_seconds = max(2.0, float(self.settings.retrieval_provider_timeout_seconds))
        self.semantic = semantic_client or SemanticScholarClient()
        self.openalex = openalex_client or OpenAlexClient()
        self.providers = self._build_provider_registry()

    def search_papers(
        self,
        *,
        query: str,
        limit: int,
        offset: int = 0,
        preferred_provider: str = "semantic_scholar",
    ) -> dict[str, Any]:
        safe_query = str(query or "").strip()
        if not safe_query:
            return {
                "provider": "mock",
                "providers_used": [],
                "papers": [],
                "status": "fallback",
                "elapsed_seconds": 0.0,
                "used_fallback": False,
                "source_stats": [],
            }

        safe_limit = max(1, min(int(limit), 120))
        provider_order = self._ordered_provider_names(preferred_provider=preferred_provider, for_seed=False)
        if not provider_order:
            return {
                "provider": "mock",
                "providers_used": [],
                "papers": [],
                "status": "fallback",
                "elapsed_seconds": 0.0,
                "used_fallback": False,
                "source_stats": [],
            }

        search_start = perf_counter()
        executions = self._search_parallel(
            provider_order=provider_order,
            query=safe_query,
            limit=safe_limit,
            offset=max(0, int(offset)),
        )
        ranked_results = self._rank_and_merge(executions=executions, limit=safe_limit)
        provider = self._resolve_primary_provider(
            preferred_provider=preferred_provider,
            providers_used=ranked_results["providers_used"],
        )
        preferred_normalized = self._normalize_provider_name(preferred_provider)
        used_fallback = bool(
            preferred_normalized
            and preferred_normalized in provider_order
            and preferred_normalized not in ranked_results["providers_used"]
            and ranked_results["providers_used"]
        )

        return {
            "provider": provider if ranked_results["papers"] else "mock",
            "providers_used": ranked_results["providers_used"],
            "papers": ranked_results["papers"],
            "status": "done" if ranked_results["papers"] else "fallback",
            "elapsed_seconds": perf_counter() - search_start,
            "used_fallback": used_fallback,
            "source_stats": self._serialize_stats(executions),
        }

    def fetch_seed_paper(
        self,
        *,
        input_type: str,
        input_value: str,
        reference_limit: int,
        citation_limit: int,
        preferred_provider: str = "semantic_scholar",
    ) -> dict[str, Any]:
        normalized_input_type = str(input_type or "").strip().lower()
        provider_order = self._ordered_provider_names(
            preferred_provider=preferred_provider,
            for_seed=True,
            input_type=normalized_input_type,
        )
        if not provider_order:
            return {
                "provider": "mock",
                "seed_paper": {},
                "providers_used": [],
                "status": "fallback",
                "source_stats": [],
            }

        executions = self._seed_parallel(
            provider_order=provider_order,
            input_type=normalized_input_type,
            input_value=str(input_value or "").strip(),
            reference_limit=max(1, int(reference_limit)),
            citation_limit=max(1, int(citation_limit)),
        )

        selected_provider = ""
        selected_paper: dict[str, Any] = {}
        for provider_name in provider_order:
            matched = next((item for item in executions if item.provider == provider_name), None)
            if not matched:
                continue
            if matched.papers:
                selected_provider = provider_name
                selected_paper = self._normalize_seed_paper(matched.papers[0])
                break

        providers_used = [item.provider for item in executions if item.papers]
        return {
            "provider": selected_provider or "mock",
            "seed_paper": selected_paper,
            "providers_used": providers_used,
            "status": "done" if selected_paper else "fallback",
            "source_stats": self._serialize_stats(executions),
        }

    def _build_provider_registry(self) -> dict[str, RetrievalProvider]:
        providers: dict[str, RetrievalProvider] = {}
        if self.settings.retrieval_enable_semantic_scholar:
            providers["semantic_scholar"] = SemanticScholarProvider(self.semantic)
        if self.settings.retrieval_enable_openalex:
            providers["openalex"] = OpenAlexProvider(self.openalex)
        if self.settings.retrieval_enable_arxiv:
            providers["arxiv"] = ArxivProvider()
        return providers

    def _ordered_provider_names(
        self,
        *,
        preferred_provider: str,
        for_seed: bool,
        input_type: str = "",
    ) -> list[str]:
        preferred = self._normalize_provider_name(preferred_provider)
        available = list(self.providers.keys())
        if for_seed:
            available = [
                name
                for name in available
                if self.providers[name].supports_seed_input(input_type)
            ]
        if not available:
            return []

        ordered: list[str] = []
        if preferred and preferred in available:
            ordered.append(preferred)

        default_priority = [
            "semantic_scholar",
            "openalex",
            "arxiv",
        ]
        for name in default_priority:
            if name in available and name not in ordered:
                ordered.append(name)
        for name in available:
            if name not in ordered:
                ordered.append(name)
        return ordered

    def _search_parallel(
        self,
        *,
        provider_order: list[str],
        query: str,
        limit: int,
        offset: int,
    ) -> list[_ProviderExecution]:
        if not provider_order:
            return []

        max_workers = max(1, min(self.max_workers, len(provider_order)))
        futures: dict[Future[tuple[list[dict[str, Any]], float]], str] = {}
        executions: list[_ProviderExecution] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for name in provider_order:
                provider = self.providers[name]
                futures[
                    executor.submit(self._run_search_call, provider, query, limit, offset)
                ] = name

            done, pending = wait(set(futures.keys()), timeout=self.provider_timeout_seconds)
            for future in pending:
                provider_name = futures[future]
                future.cancel()
                executions.append(
                    _ProviderExecution(
                        provider=provider_name,
                        papers=[],
                        elapsed_seconds=self.provider_timeout_seconds,
                        error="timeout",
                    )
                )

            for future in done:
                provider_name = futures[future]
                try:
                    papers, elapsed_seconds = future.result()
                    executions.append(
                        _ProviderExecution(
                            provider=provider_name,
                            papers=[self._normalize_paper(item) for item in papers],
                            elapsed_seconds=elapsed_seconds,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    executions.append(
                        _ProviderExecution(
                            provider=provider_name,
                            papers=[],
                            elapsed_seconds=0.0,
                            error=str(exc),
                        )
                    )

        execution_by_provider = {item.provider: item for item in executions}
        return [
            execution_by_provider.get(name)
            or _ProviderExecution(provider=name, papers=[], elapsed_seconds=0.0, error="not_executed")
            for name in provider_order
        ]

    def _seed_parallel(
        self,
        *,
        provider_order: list[str],
        input_type: str,
        input_value: str,
        reference_limit: int,
        citation_limit: int,
    ) -> list[_ProviderExecution]:
        if not provider_order:
            return []

        max_workers = max(1, min(self.max_workers, len(provider_order)))
        futures: dict[Future[tuple[dict[str, Any] | None, float]], str] = {}
        executions: list[_ProviderExecution] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for name in provider_order:
                provider = self.providers[name]
                futures[
                    executor.submit(
                        self._run_seed_call,
                        provider,
                        input_type,
                        input_value,
                        reference_limit,
                        citation_limit,
                    )
                ] = name

            done, pending = wait(set(futures.keys()), timeout=self.provider_timeout_seconds)
            for future in pending:
                provider_name = futures[future]
                future.cancel()
                executions.append(
                    _ProviderExecution(
                        provider=provider_name,
                        papers=[],
                        elapsed_seconds=self.provider_timeout_seconds,
                        error="timeout",
                    )
                )

            for future in done:
                provider_name = futures[future]
                try:
                    paper, elapsed_seconds = future.result()
                    executions.append(
                        _ProviderExecution(
                            provider=provider_name,
                            papers=[paper] if isinstance(paper, dict) else [],
                            elapsed_seconds=elapsed_seconds,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    executions.append(
                        _ProviderExecution(
                            provider=provider_name,
                            papers=[],
                            elapsed_seconds=0.0,
                            error=str(exc),
                        )
                    )

        execution_by_provider = {item.provider: item for item in executions}
        return [
            execution_by_provider.get(name)
            or _ProviderExecution(provider=name, papers=[], elapsed_seconds=0.0, error="not_executed")
            for name in provider_order
        ]

    @staticmethod
    def _run_search_call(
        provider: RetrievalProvider,
        query: str,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], float]:
        start = perf_counter()
        papers = provider.search_papers(query=query, limit=limit, offset=offset)
        return papers, perf_counter() - start

    @staticmethod
    def _run_seed_call(
        provider: RetrievalProvider,
        input_type: str,
        input_value: str,
        reference_limit: int,
        citation_limit: int,
    ) -> tuple[dict[str, Any] | None, float]:
        start = perf_counter()
        paper = provider.fetch_seed_paper(
            input_type=input_type,
            input_value=input_value,
            reference_limit=reference_limit,
            citation_limit=citation_limit,
        )
        return paper, perf_counter() - start

    def _rank_and_merge(self, *, executions: list[_ProviderExecution], limit: int) -> dict[str, Any]:
        score_by_key: defaultdict[str, float] = defaultdict(float)
        paper_by_key: dict[str, dict[str, Any]] = {}
        source_by_key: defaultdict[str, set[str]] = defaultdict(set)

        for execution in executions:
            papers = execution.papers
            for rank, paper in enumerate(papers):
                normalized = self._normalize_paper(paper)
                merge_key = self._paper_merge_key(normalized)
                if not merge_key:
                    continue
                score_by_key[merge_key] += self._rank_score(rank, normalized)
                source_by_key[merge_key].add(execution.provider)
                if merge_key in paper_by_key:
                    paper_by_key[merge_key] = self._merge_two_papers(paper_by_key[merge_key], normalized)
                else:
                    paper_by_key[merge_key] = normalized

        ranked_keys = sorted(score_by_key.keys(), key=lambda item: score_by_key[item], reverse=True)
        merged: list[dict[str, Any]] = []
        providers_used: set[str] = set()
        for key in ranked_keys[: max(1, limit)]:
            paper = dict(paper_by_key[key])
            source_providers = sorted(source_by_key[key])
            if source_providers:
                paper["source_providers"] = source_providers
                providers_used.update(source_providers)
            merged.append(paper)

        return {
            "papers": merged,
            "providers_used": sorted(providers_used),
        }

    def _resolve_primary_provider(self, *, preferred_provider: str, providers_used: list[str]) -> str:
        normalized_preferred = self._normalize_provider_name(preferred_provider)
        if normalized_preferred and normalized_preferred in providers_used:
            return normalized_preferred
        if providers_used:
            return providers_used[0]
        return "mock"

    def _serialize_stats(self, executions: list[_ProviderExecution]) -> list[dict[str, Any]]:
        stats: list[dict[str, Any]] = []
        for item in executions:
            if item.error and item.error != "timeout":
                logger.debug("provider %s retrieval error: %s", item.provider, item.error)
            stats.append(
                {
                    "provider": item.provider,
                    "status": "fallback" if item.error else "done",
                    "count": len(item.papers),
                    "elapsed_ms": int(max(0.0, item.elapsed_seconds) * 1000),
                    "error": item.error,
                }
            )
        return stats

    def _normalize_paper(self, paper: dict[str, Any] | None) -> dict[str, Any]:
        payload = paper if isinstance(paper, dict) else {}
        title = str(payload.get("title") or "").strip()
        paper_id = str(payload.get("paper_id") or payload.get("id") or "").strip()

        return {
            "paper_id": paper_id,
            "title": title,
            "abstract": str(payload.get("abstract") or "").strip(),
            "year": self._safe_int_or_none(payload.get("year")),
            "month": self._safe_int_or_none(payload.get("month")),
            "publication_date": str(payload.get("publication_date") or "").strip(),
            "citation_count": self._safe_int(payload.get("citation_count")),
            "venue": str(payload.get("venue") or "Unknown Venue").strip() or "Unknown Venue",
            "fields_of_study": self._normalize_text_list(payload.get("fields_of_study"), max_size=8),
            "authors": self._normalize_text_list(payload.get("authors"), max_size=12),
            "url": self._normalize_url(payload.get("url")),
        }

    def _normalize_seed_paper(self, paper: dict[str, Any] | None) -> dict[str, Any]:
        payload = paper if isinstance(paper, dict) else {}
        normalized = self._normalize_paper(payload)

        references: list[dict[str, Any]] = []
        for item in payload.get("references") or []:
            if not isinstance(item, dict):
                continue
            related = self._normalize_paper(item)
            if str(related.get("paper_id") or "").strip() and str(related.get("title") or "").strip():
                references.append(related)

        citations: list[dict[str, Any]] = []
        for item in payload.get("citations") or []:
            if not isinstance(item, dict):
                continue
            related = self._normalize_paper(item)
            if str(related.get("paper_id") or "").strip() and str(related.get("title") or "").strip():
                citations.append(related)

        external_ids_raw = payload.get("external_ids") or {}
        external_ids: dict[str, str] = {}
        if isinstance(external_ids_raw, dict):
            for key, value in external_ids_raw.items():
                key_text = str(key or "").strip()
                value_text = str(value or "").strip()
                if key_text and value_text:
                    external_ids[key_text] = value_text

        normalized["references"] = references
        normalized["citations"] = citations
        normalized["reference_count"] = max(
            self._safe_int(payload.get("reference_count")),
            len(references),
        )
        if external_ids:
            normalized["external_ids"] = external_ids
        return normalized

    def _paper_merge_key(self, paper: dict[str, Any]) -> str:
        paper_id = str(paper.get("paper_id") or "").strip().lower()
        doi = self._extract_doi(paper)
        if doi:
            return f"doi:{doi}"

        if paper_id.startswith("arxiv:"):
            raw_id = paper_id.split(":", 1)[1]
            normalized = re.sub(r"v\d+$", "", raw_id, flags=re.IGNORECASE)
            if normalized:
                return f"arxiv:{normalized}"

        title_key = self._title_key(paper.get("title"))
        year = self._safe_int(paper.get("year"))
        if title_key and year > 0:
            return f"title-year:{title_key}:{year}"
        if title_key:
            return f"title:{title_key}"
        if paper_id:
            return f"id:{paper_id}"
        return ""

    def _rank_score(self, rank: int, paper: dict[str, Any]) -> float:
        base_rank = 1.0 / float(rank + 1)
        citation_bonus = min(0.5, math.log1p(self._safe_int(paper.get("citation_count"))) / 12.0)
        year = self._safe_int(paper.get("year"))
        current_year = datetime_utc_year()
        recency_bonus = 0.0
        if year > 0:
            delta = max(0, current_year - year)
            recency_bonus = max(0.0, 0.25 - 0.03 * float(delta))
        return base_rank + citation_bonus + recency_bonus

    def _merge_two_papers(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        merged = dict(left)
        if len(str(right.get("abstract") or "")) > len(str(merged.get("abstract") or "")):
            merged["abstract"] = right.get("abstract") or ""
        merged["citation_count"] = max(
            self._safe_int(merged.get("citation_count")),
            self._safe_int(right.get("citation_count")),
        )
        merged["year"] = self._prefer_positive_int(merged.get("year"), right.get("year"))
        merged["month"] = self._prefer_positive_int(merged.get("month"), right.get("month"))
        merged["publication_date"] = str(
            merged.get("publication_date") or right.get("publication_date") or ""
        ).strip()
        merged["venue"] = str(merged.get("venue") or "Unknown Venue").strip() or str(
            right.get("venue") or "Unknown Venue"
        ).strip() or "Unknown Venue"
        merged["fields_of_study"] = self._merge_unique_texts(
            merged.get("fields_of_study"),
            right.get("fields_of_study"),
            limit=8,
        )
        merged["authors"] = self._merge_unique_texts(merged.get("authors"), right.get("authors"), limit=12)
        merged["url"] = self._normalize_url(merged.get("url")) or self._normalize_url(right.get("url"))
        if not str(merged.get("paper_id") or "").strip():
            merged["paper_id"] = str(right.get("paper_id") or "").strip()
        if not str(merged.get("title") or "").strip():
            merged["title"] = str(right.get("title") or "").strip()
        return merged

    @classmethod
    def _extract_doi(cls, paper: dict[str, Any]) -> str:
        for candidate in (
            str(paper.get("paper_id") or "").strip(),
            str(paper.get("url") or "").strip(),
            str(paper.get("publication_date") or "").strip(),
            str(paper.get("title") or "").strip(),
        ):
            if not candidate:
                continue
            match = cls._DOI_PATTERN.search(candidate)
            if match:
                return match.group(0).lower().rstrip(").,;")
        return ""

    @staticmethod
    def _normalize_provider_name(name: str) -> str:
        value = str(name or "").strip().lower()
        if value.startswith("semantic"):
            return "semantic_scholar"
        if value.startswith("openalex"):
            return "openalex"
        if value.startswith("arxiv"):
            return "arxiv"
        return value

    @staticmethod
    def _normalize_text_list(raw_values: Any, *, max_size: int) -> list[str]:
        items: list[str] = []
        for raw in raw_values or []:
            text = str(raw or "").strip()
            if not text:
                continue
            items.append(text)
            if len(items) >= max(1, max_size):
                break
        return list(dict.fromkeys(items))

    @staticmethod
    def _merge_unique_texts(left: Any, right: Any, *, limit: int) -> list[str]:
        merged: list[str] = []
        for raw in [*(left or []), *(right or [])]:
            text = str(raw or "").strip()
            if not text:
                continue
            merged.append(text)
            if len(merged) >= max(1, limit):
                break
        return list(dict.fromkeys(merged))

    @staticmethod
    def _normalize_url(raw_value: Any) -> str | None:
        value = str(raw_value or "").strip()
        if not value:
            return None
        return value

    @staticmethod
    def _title_key(raw_text: Any) -> str:
        value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(raw_text or "").lower())
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _safe_int(raw_value: Any) -> int:
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_int_or_none(raw_value: Any) -> int | None:
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _prefer_positive_int(left: Any, right: Any) -> int | None:
        left_val = MultiSourceRetriever._safe_int_or_none(left)
        right_val = MultiSourceRetriever._safe_int_or_none(right)
        if left_val and right_val:
            return max(left_val, right_val)
        return left_val or right_val


@lru_cache
def get_multi_source_retriever() -> MultiSourceRetriever:
    return MultiSourceRetriever()


def datetime_utc_year() -> int:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).year
