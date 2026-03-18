from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from core import llm_client
from external.openalex import OpenAlexClient, OpenAlexClientError
from external.semantic_scholar import (
    SemanticScholarClient,
    SemanticScholarClientError,
    SemanticScholarNotFoundError,
)
from models.schemas import (
    LineageEdge,
    LineagePaper,
    LineageResponse,
    LineageStats,
)
from repositories.neo4j_repository import Neo4jRepository, get_neo4j_repository

logger = logging.getLogger(__name__)

VALID_CITATION_TYPES: set[str] = {
    "supporting",
    "contradicting",
    "extending",
    "migrating",
    "mentioning",
}
_CACHE_TTL = timedelta(days=7)
_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "lineage"


def _normalize_paper_id(paper_id: str) -> str:
    value = str(paper_id or "").strip()
    if not value:
        raise ValueError("paper_id must not be empty")
    return value


def _normalize_citation_type(raw_value: str | None) -> str:
    normalized = str(raw_value or "").strip().lower()
    if normalized in VALID_CITATION_TYPES:
        return normalized
    return "mentioning"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cache_path(
    paper_id: str,
    *,
    ancestor_depth: int,
    descendant_depth: int,
    citation_types: list[str],
) -> Path:
    key_payload = {
        "paper_id": paper_id,
        "ancestor_depth": ancestor_depth,
        "descendant_depth": descendant_depth,
        "citation_types": sorted(citation_types),
        "version": 1,
    }
    key = hashlib.md5(json.dumps(key_payload, sort_keys=True).encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{key}.json"


def get_cached_lineage(
    paper_id: str,
    *,
    ancestor_depth: int,
    descendant_depth: int,
    citation_types: list[str],
) -> LineageResponse | None:
    cache_file = _cache_path(
        paper_id,
        ancestor_depth=ancestor_depth,
        descendant_depth=descendant_depth,
        citation_types=citation_types,
    )
    if not cache_file.exists():
        return None

    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("lineage cache read failed: %s", cache_file)
        return None

    cached_at_raw = payload.get("cached_at")
    try:
        cached_at = datetime.fromisoformat(str(cached_at_raw))
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None

    if datetime.now(timezone.utc) - cached_at > _CACHE_TTL:
        return None

    payload.pop("cached_at", None)
    payload["cached"] = True
    try:
        return LineageResponse.model_validate(payload)
    except Exception:  # noqa: BLE001
        logger.warning("lineage cache payload parse failed: %s", cache_file)
        return None


def set_cached_lineage(
    paper_id: str,
    *,
    ancestor_depth: int,
    descendant_depth: int,
    citation_types: list[str],
    response: LineageResponse,
) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(
        paper_id,
        ancestor_depth=ancestor_depth,
        descendant_depth=descendant_depth,
        citation_types=citation_types,
    )
    payload = response.model_dump(mode="json")
    payload["cached_at"] = datetime.now(timezone.utc).isoformat()
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_cached_lineage(
    paper_id: str,
    *,
    ancestor_depth: int,
    descendant_depth: int,
    citation_types: list[str],
) -> None:
    cache_file = _cache_path(
        paper_id,
        ancestor_depth=ancestor_depth,
        descendant_depth=descendant_depth,
        citation_types=citation_types,
    )
    if cache_file.exists():
        cache_file.unlink(missing_ok=True)


async def query_lineage_from_neo4j(
    repository: Neo4jRepository,
    paper_id: str,
    *,
    ancestor_depth: int,
    descendant_depth: int,
) -> dict[str, Any]:
    ancestor_limit = max(8, min(ancestor_depth * 10, 60))
    descendant_limit = max(8, min(descendant_depth * 10, 60))
    return await asyncio.to_thread(
        repository.fetch_lineage_neighborhood,
        paper_id,
        ancestor_limit=ancestor_limit,
        descendant_limit=descendant_limit,
    )


def _extract_arxiv_id(raw: dict[str, Any]) -> str | None:
    explicit = str(raw.get("arxiv_id") or raw.get("arxivId") or "").strip()
    if explicit:
        return explicit
    external_ids = raw.get("external_ids") or raw.get("externalIds") or {}
    if isinstance(external_ids, dict):
        arxiv_value = str(external_ids.get("ArXiv") or "").strip()
        if arxiv_value:
            return arxiv_value
    return None


def _normalize_doi_value(raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    value = re.sub(r"^doi:\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.IGNORECASE).strip()
    return value


def _extract_doi(raw: dict[str, Any]) -> str | None:
    explicit = _normalize_doi_value(raw.get("doi"))
    if explicit:
        return explicit

    external_ids = raw.get("external_ids") or raw.get("externalIds") or {}
    if isinstance(external_ids, dict):
        doi_value = _normalize_doi_value(external_ids.get("DOI") or external_ids.get("doi"))
        if doi_value:
            return doi_value
    return None


def _normalize_authors(raw: dict[str, Any]) -> list[str]:
    value = raw.get("authors") or []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    authors: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            authors.append(item.strip())
            continue
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                authors.append(name)
    return authors


def _coerce_raw_paper(raw: dict[str, Any]) -> dict[str, Any]:
    paper_id = str(raw.get("paper_id") or raw.get("paperId") or raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not paper_id or not title:
        return {}

    abstract = (
        str(raw.get("abstract") or "").strip()
        or str(raw.get("summary") or "").strip()
        or str(raw.get("description") or "").strip()
    ) or None
    publication_date = (
        str(raw.get("publication_date") or "").strip()
        or str(raw.get("publicationDate") or "").strip()
        or str(raw.get("published_at") or "").strip()
        or str(raw.get("published_date") or "").strip()
        or None
    )

    return {
        "paper_id": paper_id,
        "title": title,
        "authors": _normalize_authors(raw),
        "year": _safe_int(raw.get("year"), default=0) or None,
        "publication_date": publication_date,
        "citation_count": max(0, _safe_int(raw.get("citation_count") or raw.get("citationCount"), default=0)),
        "venue": str(raw.get("venue") or "").strip() or None,
        "abstract": abstract,
        "arxiv_id": _extract_arxiv_id(raw),
        "doi": _extract_doi(raw),
        "ctype": _normalize_citation_type(raw.get("ctype") or raw.get("relation_type") or "mentioning"),
        "hop": max(1, _safe_int(raw.get("hop"), default=1)),
    }


def _paper_has_abstract(raw: dict[str, Any] | None) -> bool:
    if not isinstance(raw, dict):
        return False
    return bool(str(raw.get("abstract") or "").strip())


def _paper_has_publication_date(raw: dict[str, Any] | None) -> bool:
    if not isinstance(raw, dict):
        return False
    return bool(str(raw.get("publication_date") or "").strip())


def _paper_has_authors(raw: dict[str, Any] | None) -> bool:
    if not isinstance(raw, dict):
        return False
    authors = raw.get("authors") or []
    if isinstance(authors, str):
        return bool(authors.strip())
    if isinstance(authors, list):
        return any(bool(str(item or "").strip()) for item in authors)
    return False


def _coverage_by(papers: list[dict[str, Any]], checker: Any) -> float:
    if not papers:
        return 0.0
    count = sum(1 for paper in papers if checker(paper))
    return count / max(1, len(papers))


def _needs_metadata_enrichment(
    root: dict[str, Any],
    ancestors: list[dict[str, Any]],
    descendants: list[dict[str, Any]],
) -> bool:
    if not _paper_has_abstract(root):
        return True
    if not _paper_has_publication_date(root):
        return True
    if not _paper_has_authors(root):
        return True
    related = [*ancestors, *descendants]
    if not related:
        return False
    # Keep refreshing when related-paper metadata coverage is very low.
    return (
        _coverage_by(related, _paper_has_abstract) < 0.25
        or _coverage_by(related, _paper_has_publication_date) < 0.25
        or _coverage_by(related, _paper_has_authors) < 0.25
    )


def _merge_raw_paper(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if not base:
        return dict(incoming)
    if not incoming:
        return dict(base)

    merged = dict(base)
    base_abstract = str(base.get("abstract") or "").strip()
    incoming_abstract = str(incoming.get("abstract") or "").strip()
    base_publication_date = str(base.get("publication_date") or "").strip()
    incoming_publication_date = str(incoming.get("publication_date") or "").strip()
    base_authors = _normalize_authors(base)
    incoming_authors = _normalize_authors(incoming)

    if not str(merged.get("title") or "").strip() and str(incoming.get("title") or "").strip():
        merged["title"] = incoming.get("title")
    if not merged.get("year") and incoming.get("year"):
        merged["year"] = incoming.get("year")
    if len(incoming_publication_date) > len(base_publication_date):
        merged["publication_date"] = incoming_publication_date
    if not merged.get("venue") and incoming.get("venue"):
        merged["venue"] = incoming.get("venue")
    if len(incoming_authors) > len(base_authors):
        merged["authors"] = incoming_authors
    if len(incoming_abstract) > len(base_abstract):
        merged["abstract"] = incoming_abstract
    merged["citation_count"] = max(
        _safe_int(base.get("citation_count"), default=0),
        _safe_int(incoming.get("citation_count"), default=0),
    )

    for key in ("arxiv_id", "doi", "ctype", "hop", "relation_type", "relation_description"):
        if not merged.get(key) and incoming.get(key):
            merged[key] = incoming.get(key)
    return merged


def _merge_raw_paper_lists(
    base_items: list[dict[str, Any]],
    incoming_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_map: dict[str, int] = {}

    for item in base_items:
        paper_id = str(item.get("paper_id") or "").strip()
        if not paper_id:
            continue
        index_map[paper_id] = len(merged)
        merged.append(dict(item))

    for item in incoming_items:
        paper_id = str(item.get("paper_id") or "").strip()
        if not paper_id:
            continue
        target_index = index_map.get(paper_id)
        if target_index is None:
            index_map[paper_id] = len(merged)
            merged.append(dict(item))
            continue
        merged[target_index] = _merge_raw_paper(merged[target_index], item)

    return merged


async def fetch_lineage_from_semantic(
    client: SemanticScholarClient,
    paper_id: str,
    *,
    ancestor_depth: int,
    descendant_depth: int,
) -> dict[str, Any]:
    # Keep first response bounded for latency and LLM cost.
    reference_limit = max(8, min(ancestor_depth * 10, 40))
    citation_limit = max(8, min(descendant_depth * 10, 40))

    try:
        payload = await asyncio.to_thread(
            client.fetch_paper,
            paper_id,
            reference_limit,
            citation_limit,
        )
    except SemanticScholarClientError:
        payload = await _fetch_lineage_from_semantic_http(
            client,
            paper_id,
            reference_limit=reference_limit,
            citation_limit=citation_limit,
        )

    root = _coerce_raw_paper(payload)
    if not root:
        return {"root": None, "ancestors": [], "descendants": []}

    ancestors = [_coerce_raw_paper(item) for item in (payload.get("references") or [])]
    descendants = [_coerce_raw_paper(item) for item in (payload.get("citations") or [])]
    return {
        "root": root,
        "ancestors": [item for item in ancestors if item],
        "descendants": [item for item in descendants if item],
    }


def _normalize_arxiv_candidate(raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    value = re.sub(r"^arxiv:\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\.pdf$", "", value, flags=re.IGNORECASE).strip()
    return value


def _build_semantic_candidate_ids(
    seed_paper_id: str,
    root_raw: dict[str, Any],
    openalex_payload: dict[str, Any] | None,
) -> list[str]:
    candidates: list[str] = []

    def append_candidate(value: str) -> None:
        normalized = str(value or "").strip()
        if not normalized:
            return
        if normalized not in candidates:
            candidates.append(normalized)

    append_candidate(seed_paper_id)
    append_candidate(_normalize_doi_value(seed_paper_id))
    append_candidate(_normalize_arxiv_candidate(seed_paper_id))

    root_doi = _extract_doi(root_raw)
    root_arxiv = _extract_arxiv_id(root_raw)
    if root_doi:
        append_candidate(root_doi)
        append_candidate(f"DOI:{root_doi}")
    if root_arxiv:
        append_candidate(root_arxiv)
        append_candidate(f"ARXIV:{root_arxiv}")

    if openalex_payload:
        openalex_doi = _extract_doi(openalex_payload)
        openalex_arxiv = _extract_arxiv_id(openalex_payload)
        if openalex_doi:
            append_candidate(openalex_doi)
            append_candidate(f"DOI:{openalex_doi}")
        if openalex_arxiv:
            append_candidate(openalex_arxiv)
            append_candidate(f"ARXIV:{openalex_arxiv}")

    return candidates


def _build_openalex_candidate_ids(
    seed_paper_id: str,
    root_raw: dict[str, Any],
    openalex_payload: dict[str, Any] | None,
) -> list[str]:
    candidates: list[str] = []

    def append_candidate(value: Any) -> None:
        normalized = str(value or "").strip()
        if not normalized:
            return
        if normalized not in candidates:
            candidates.append(normalized)

    append_candidate(seed_paper_id)
    append_candidate(_normalize_doi_value(seed_paper_id))
    append_candidate(_normalize_arxiv_candidate(seed_paper_id))
    append_candidate(root_raw.get("paper_id"))

    root_doi = _extract_doi(root_raw)
    root_arxiv = _extract_arxiv_id(root_raw)
    if root_doi:
        append_candidate(root_doi)
        append_candidate(f"DOI:{root_doi}")
    if root_arxiv:
        append_candidate(root_arxiv)
        append_candidate(f"ARXIV:{root_arxiv}")

    if openalex_payload:
        append_candidate(openalex_payload.get("paper_id"))
        openalex_doi = _extract_doi(openalex_payload)
        openalex_arxiv = _extract_arxiv_id(openalex_payload)
        if openalex_doi:
            append_candidate(openalex_doi)
            append_candidate(f"DOI:{openalex_doi}")
        if openalex_arxiv:
            append_candidate(openalex_arxiv)
            append_candidate(f"ARXIV:{openalex_arxiv}")

    return candidates


async def fetch_lineage_from_openalex(
    client: OpenAlexClient,
    paper_id: str,
    *,
    ancestor_depth: int,
    descendant_depth: int,
) -> dict[str, Any]:
    reference_limit = max(8, min(ancestor_depth * 10, 40))
    citation_limit = max(8, min(descendant_depth * 10, 40))
    normalized_input = str(paper_id or "").strip()
    if not normalized_input:
        return {"root": None, "ancestors": [], "descendants": []}

    normalized_doi = _normalize_doi_value(normalized_input)
    normalized_arxiv = _normalize_arxiv_candidate(normalized_input)

    def fetch_payload() -> dict[str, Any] | None:
        lowered = normalized_input.lower()
        if lowered.startswith("openalex:") or normalized_input.upper().startswith("W") or lowered.startswith("https://openalex.org/"):
            return client.fetch_paper(
                normalized_input,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        if lowered.startswith("doi:") or (normalized_doi and SemanticScholarClient._DOI_PATTERN.match(normalized_doi)):
            return client.fetch_paper_by_doi(
                normalized_doi,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        if lowered.startswith("arxiv:") or (normalized_arxiv and SemanticScholarClient._ARXIV_PATTERN.match(normalized_arxiv)):
            return client.fetch_paper_by_arxiv_id(
                normalized_arxiv,
                reference_limit=reference_limit,
                citation_limit=citation_limit,
            )
        return None

    payload = await asyncio.to_thread(fetch_payload)
    root = _coerce_raw_paper(payload or {})
    if not root:
        return {"root": None, "ancestors": [], "descendants": []}

    ancestors = [_coerce_raw_paper(item) for item in ((payload or {}).get("references") or [])]
    descendants = [_coerce_raw_paper(item) for item in ((payload or {}).get("citations") or [])]
    return {
        "root": root,
        "ancestors": [item for item in ancestors if item],
        "descendants": [item for item in descendants if item],
    }


async def _fetch_lineage_from_semantic_http(
    client: SemanticScholarClient,
    paper_id: str,
    *,
    reference_limit: int,
    citation_limit: int,
) -> dict[str, Any]:
    normalized_id = SemanticScholarClient.normalize_paper_id(paper_id)
    base_url = SemanticScholarClient.BASE_URL
    headers = {"Accept": "application/json"}
    if client.api_key:
        headers["x-api-key"] = client.api_key

    paper_fields = ",".join(
        [
            "paperId",
            "title",
            "abstract",
            "year",
            "citationCount",
            "authors",
            "venue",
            "externalIds",
        ]
    )

    root_payload = await _semantic_get_with_retry(
        f"{base_url}/paper/{quote(normalized_id, safe='')}",
        params={"fields": paper_fields},
        headers=headers,
    )
    if root_payload is None:
        raise SemanticScholarClientError("semantic_scholar_http_fallback_failed")

    root = {
        "paper_id": str(root_payload.get("paperId") or ""),
        "title": str(root_payload.get("title") or ""),
        "abstract": str(root_payload.get("abstract") or ""),
        "year": root_payload.get("year"),
        "citation_count": _safe_int(root_payload.get("citationCount"), default=0),
        "authors": root_payload.get("authors") or [],
        "venue": str(root_payload.get("venue") or ""),
        "external_ids": root_payload.get("externalIds") or {},
    }

    references_payload = await _semantic_get_with_retry(
        f"{base_url}/paper/{quote(normalized_id, safe='')}/references",
        params={
            "fields": f"citedPaper.{paper_fields}",
            "limit": max(1, min(reference_limit, 100)),
        },
        headers=headers,
    )
    citations_payload = await _semantic_get_with_retry(
        f"{base_url}/paper/{quote(normalized_id, safe='')}/citations",
        params={
            "fields": f"citingPaper.{paper_fields}",
            "limit": max(1, min(citation_limit, 100)),
        },
        headers=headers,
    )

    references: list[dict[str, Any]] = []
    for item in (references_payload or {}).get("data", []):
        paper = item.get("citedPaper") or {}
        if not isinstance(paper, dict):
            continue
        references.append(
            {
                "paper_id": str(paper.get("paperId") or ""),
                "title": str(paper.get("title") or ""),
                "abstract": str(paper.get("abstract") or ""),
                "year": paper.get("year"),
                "citation_count": _safe_int(paper.get("citationCount"), default=0),
                "authors": paper.get("authors") or [],
                "venue": str(paper.get("venue") or ""),
                "external_ids": paper.get("externalIds") or {},
            }
        )

    citations: list[dict[str, Any]] = []
    for item in (citations_payload or {}).get("data", []):
        paper = item.get("citingPaper") or {}
        if not isinstance(paper, dict):
            continue
        citations.append(
            {
                "paper_id": str(paper.get("paperId") or ""),
                "title": str(paper.get("title") or ""),
                "abstract": str(paper.get("abstract") or ""),
                "year": paper.get("year"),
                "citation_count": _safe_int(paper.get("citationCount"), default=0),
                "authors": paper.get("authors") or [],
                "venue": str(paper.get("venue") or ""),
                "external_ids": paper.get("externalIds") or {},
            }
        )

    return {
        **root,
        "references": references,
        "citations": citations,
    }


async def _semantic_get_with_retry(
    url: str,
    *,
    params: dict[str, Any],
    headers: dict[str, str],
    retries: int = 3,
) -> dict[str, Any] | None:
    timeout = 20.0
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                response = await client.get(url, params=params)
            if response.status_code == 404:
                raise SemanticScholarNotFoundError("paper_not_found")
            if response.status_code == 429:
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code >= 500:
                await asyncio.sleep(1 + attempt)
                continue
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return None
        except SemanticScholarNotFoundError:
            raise
        except Exception:  # noqa: BLE001
            if attempt >= retries - 1:
                return None
            await asyncio.sleep(1 + attempt)
    return None


def _chunk(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _extract_json_block(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.replace("json\n", "", 1).strip()

    start_obj = stripped.find("{")
    start_arr = stripped.find("[")
    starts = [position for position in (start_obj, start_arr) if position >= 0]
    if not starts:
        return stripped
    start = min(starts)
    return stripped[start:]


def _parse_classification_payload(content: str, expected_count: int) -> list[dict[str, Any]]:
    raw = _extract_json_block(content)
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []

    if isinstance(parsed, dict):
        items = parsed.get("items")
        if isinstance(items, list):
            parsed = items

    if not isinstance(parsed, list):
        return []

    output: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        index = _safe_int(item.get("index"), default=-1)
        if index < 1 or index > expected_count:
            continue
        ctype = _normalize_citation_type(item.get("type"))
        reason = str(item.get("reason") or "").strip()
        output.append({"index": index, "type": ctype, "reason": reason})
    return output


def _classify_chunk_with_llm(
    *,
    root_title: str,
    root_abstract: str,
    papers: list[dict[str, Any]],
    direction: str,
) -> list[dict[str, Any]]:
    numbered_lines: list[str] = []
    for idx, paper in enumerate(papers, start=1):
        title = str(paper.get("title") or "Unknown Title").strip()
        year = paper.get("year") or "?"
        abstract = str(paper.get("abstract") or "").strip()
        if len(abstract) > 220:
            abstract = f"{abstract[:220]}..."
        numbered_lines.append(f"{idx}. {title} ({year})\\n摘要: {abstract}")

    relation_hint = (
        f"以下论文都被《{root_title}》引用。请判断《{root_title}》如何使用这些论文。"
        if direction == "ancestor"
        else f"以下论文都引用了《{root_title}》。请判断这些论文如何对待《{root_title}》的工作。"
    )
    prompt = "\n".join(
        [
            f"根论文: {root_title}",
            f"根摘要: {root_abstract[:320]}",
            relation_hint,
            "候选论文:",
            "\n".join(numbered_lines),
            "可选类型: extending, supporting, contradicting, migrating, mentioning",
            "返回 JSON 数组，格式 [{\"index\":1,\"type\":\"extending\",\"reason\":\"...\"}]。",
            "不要输出任何额外文本。",
        ]
    )

    completion = llm_client.chat(
        [
            {
                "role": "system",
                "content": "你是学术引用关系标注助手，只输出合法 JSON。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0,
        max_tokens=800,
    )
    content = ""
    try:
        content = str(completion.choices[0].message.content or "")
    except Exception:  # noqa: BLE001
        content = ""

    classified = _parse_classification_payload(content, len(papers))
    index_map = {item["index"]: item for item in classified}

    output: list[dict[str, Any]] = []
    for idx, paper in enumerate(papers, start=1):
        resolved = index_map.get(idx) or {"type": "mentioning", "reason": ""}
        output.append(
            {
                **paper,
                "ctype": _normalize_citation_type(resolved.get("type")),
                "relation_description": str(resolved.get("reason") or "").strip(),
            }
        )
    return output


async def classify_citations_batch(
    root_title: str,
    root_abstract: str,
    papers: list[dict[str, Any]],
    *,
    direction: str,
) -> list[dict[str, Any]]:
    if not papers:
        return []

    fallback = [{**paper, "ctype": _normalize_citation_type(paper.get("ctype")), "relation_description": ""} for paper in papers]
    if not llm_client.is_configured():
        return fallback

    try:
        chunks = _chunk(papers, 15)
        tasks = [
            asyncio.to_thread(
                _classify_chunk_with_llm,
                root_title=root_title,
                root_abstract=root_abstract,
                papers=chunk,
                direction=direction,
            )
            for chunk in chunks
        ]
        chunk_results = await asyncio.gather(*tasks)
        merged: list[dict[str, Any]] = []
        for chunk_result in chunk_results:
            merged.extend(chunk_result)
        return merged
    except Exception:  # noqa: BLE001
        logger.exception("lineage citation classification failed, fallback to mentioning")
        return fallback


def _to_lineage_paper(raw: dict[str, Any], *, node_type: str) -> LineagePaper:
    ctype = None if node_type == "root" else _normalize_citation_type(raw.get("ctype"))
    relation_description = str(raw.get("relation_description") or "").strip()
    paper_id = str(raw.get("paper_id") or "").strip()
    return LineagePaper(
        id=paper_id,
        paper_id=paper_id,
        title=str(raw.get("title") or "Unknown Paper"),
        authors=_normalize_authors(raw),
        year=raw.get("year"),
        publication_date=str(raw.get("publication_date") or "").strip() or None,
        citation_count=max(0, _safe_int(raw.get("citation_count"), default=0)),
        venue=raw.get("venue"),
        abstract=raw.get("abstract"),
        arxiv_id=_extract_arxiv_id(raw),
        node_type=node_type,  # type: ignore[arg-type]
        ctype=ctype,  # type: ignore[arg-type]
        hop=max(0, _safe_int(raw.get("hop"), default=1)),
        relation_type=ctype,  # type: ignore[arg-type]
        relation_description=relation_description,
        generation=max(0, _safe_int(raw.get("hop"), default=1)),
    )


def _apply_relevance(nodes: list[LineagePaper]) -> None:
    if not nodes:
        return
    max_citation = max(1, max(node.citation_count for node in nodes))
    for node in nodes:
        node.relevance = round(min(1.0, node.citation_count / max_citation), 3)


def _build_edges(
    root_id: str,
    ancestors: list[LineagePaper],
    descendants: list[LineagePaper],
) -> list[LineageEdge]:
    edges: list[LineageEdge] = []
    for item in ancestors:
        edges.append(
            LineageEdge(
                source=root_id,
                target=item.paper_id,
                ctype=_normalize_citation_type(item.ctype),  # type: ignore[arg-type]
                hop=max(1, item.hop),
            )
        )
    for item in descendants:
        edges.append(
            LineageEdge(
                source=item.paper_id,
                target=root_id,
                ctype=_normalize_citation_type(item.ctype),  # type: ignore[arg-type]
                hop=max(1, item.hop),
            )
        )
    return edges


def _compute_stats(ancestors: list[LineagePaper], descendants: list[LineagePaper]) -> LineageStats:
    type_distribution: dict[str, int] = {}
    years: list[int] = []

    for paper in [*ancestors, *descendants]:
        if paper.ctype:
            key = _normalize_citation_type(paper.ctype)
            type_distribution[key] = type_distribution.get(key, 0) + 1
        if isinstance(paper.year, int) and paper.year > 0:
            years.append(paper.year)

    controversy_count = type_distribution.get("contradicting", 0)
    year_range = (min(years), max(years)) if years else (0, 0)
    return LineageStats(
        total_ancestors=len(ancestors),
        total_descendants=len(descendants),
        type_distribution=type_distribution,
        has_controversy=controversy_count > 0,
        controversy_count=controversy_count,
        year_range=year_range,
    )


async def _persist_lineage_async(
    repository: Neo4jRepository,
    root: dict[str, Any],
    ancestors: list[dict[str, Any]],
    descendants: list[dict[str, Any]],
) -> None:
    await asyncio.to_thread(repository.persist_lineage_snapshot, root, ancestors, descendants)


def _sanitize_citation_filters(citation_types: list[str] | None) -> list[str]:
    normalized = [
        str(item).strip().lower()
        for item in (citation_types or [])
        if str(item).strip() and str(item).strip().lower() in VALID_CITATION_TYPES
    ]
    return sorted(set(normalized))


def _filter_by_depth_and_type(
    papers: list[LineagePaper],
    *,
    max_hop: int,
    allowed_types: set[str],
) -> list[LineagePaper]:
    output: list[LineagePaper] = []
    for paper in papers:
        if paper.hop > max_hop:
            continue
        if allowed_types and _normalize_citation_type(paper.ctype) not in allowed_types:
            continue
        output.append(paper)
    return output


async def build_lineage(
    paper_id: str,
    *,
    ancestor_depth: int = 2,
    descendant_depth: int = 2,
    citation_types: list[str] | None = None,
    force_refresh: bool = False,
) -> LineageResponse:
    safe_paper_id = _normalize_paper_id(paper_id)
    safe_ancestor_depth = max(1, min(int(ancestor_depth), 4))
    safe_descendant_depth = max(1, min(int(descendant_depth), 4))
    safe_citation_types = _sanitize_citation_filters(citation_types)
    target_ancestor_count = max(3, safe_ancestor_depth + 1)
    target_descendant_count = max(3, safe_descendant_depth + 1)

    if force_refresh:
        clear_cached_lineage(
            safe_paper_id,
            ancestor_depth=safe_ancestor_depth,
            descendant_depth=safe_descendant_depth,
            citation_types=safe_citation_types,
        )

    cached_payload = get_cached_lineage(
        safe_paper_id,
        ancestor_depth=safe_ancestor_depth,
        descendant_depth=safe_descendant_depth,
        citation_types=safe_citation_types,
    )
    if cached_payload is not None:
        return cached_payload

    repository = get_neo4j_repository()
    semantic_client = SemanticScholarClient()
    openalex_client = OpenAlexClient()

    neo4j_result = await query_lineage_from_neo4j(
        repository,
        safe_paper_id,
        ancestor_depth=safe_ancestor_depth,
        descendant_depth=safe_descendant_depth,
    )
    root_raw = _coerce_raw_paper(neo4j_result.get("root") or {})
    ancestor_raw = [_coerce_raw_paper(item) for item in (neo4j_result.get("ancestors") or [])]
    descendant_raw = [_coerce_raw_paper(item) for item in (neo4j_result.get("descendants") or [])]
    ancestor_raw = [item for item in ancestor_raw if item]
    descendant_raw = [item for item in descendant_raw if item]

    needs_semantic = (
        not root_raw
        or len(ancestor_raw) < target_ancestor_count
        or len(descendant_raw) < target_descendant_count
        or _needs_metadata_enrichment(root_raw, ancestor_raw, descendant_raw)
    )

    semantic_result: dict[str, Any] | None = None
    semantic_openalex_payload: dict[str, Any] | None = None
    semantic_error: Exception | None = None
    if safe_paper_id.lower().startswith("openalex:"):
        try:
            semantic_openalex_payload = await asyncio.to_thread(
                openalex_client.fetch_paper,
                safe_paper_id,
                1,
                1,
            )
        except OpenAlexClientError as exc:
            logger.warning("openalex seed resolve failed for lineage semantic candidates: %s", exc)

    if needs_semantic:
        semantic_candidates = _build_semantic_candidate_ids(
            safe_paper_id,
            root_raw,
            semantic_openalex_payload,
        )
        for candidate_paper_id in semantic_candidates:
            try:
                semantic_result = await fetch_lineage_from_semantic(
                    semantic_client,
                    candidate_paper_id,
                    ancestor_depth=safe_ancestor_depth,
                    descendant_depth=safe_descendant_depth,
                )
            except SemanticScholarNotFoundError as exc:
                semantic_error = exc
                continue
            except SemanticScholarClientError as exc:
                semantic_error = exc
                continue

            semantic_root = _coerce_raw_paper(semantic_result.get("root") or {})
            if semantic_root:
                root_raw = _merge_raw_paper(root_raw, semantic_root) if root_raw else semantic_root

            semantic_ancestors = [_coerce_raw_paper(item) for item in (semantic_result.get("ancestors") or [])]
            semantic_ancestors = [item for item in semantic_ancestors if item]
            if semantic_ancestors:
                if len(ancestor_raw) < target_ancestor_count:
                    ancestor_raw = semantic_ancestors
                else:
                    ancestor_raw = _merge_raw_paper_lists(ancestor_raw, semantic_ancestors)

            semantic_descendants = [_coerce_raw_paper(item) for item in (semantic_result.get("descendants") or [])]
            semantic_descendants = [item for item in semantic_descendants if item]
            if semantic_descendants:
                if len(descendant_raw) < target_descendant_count:
                    descendant_raw = semantic_descendants
                else:
                    descendant_raw = _merge_raw_paper_lists(descendant_raw, semantic_descendants)

            if (
                root_raw
                and len(ancestor_raw) >= target_ancestor_count
                and len(descendant_raw) >= target_descendant_count
                and not _needs_metadata_enrichment(root_raw, ancestor_raw, descendant_raw)
            ):
                break

    needs_openalex = (
        not root_raw
        or len(ancestor_raw) < target_ancestor_count
        or len(descendant_raw) < target_descendant_count
        or _needs_metadata_enrichment(root_raw, ancestor_raw, descendant_raw)
    )
    openalex_error: Exception | None = None
    if needs_openalex:
        openalex_candidates = _build_openalex_candidate_ids(
            safe_paper_id,
            root_raw,
            semantic_openalex_payload,
        )
        for openalex_candidate in openalex_candidates:
            try:
                openalex_result = await fetch_lineage_from_openalex(
                    openalex_client,
                    openalex_candidate,
                    ancestor_depth=safe_ancestor_depth,
                    descendant_depth=safe_descendant_depth,
                )
            except OpenAlexClientError as exc:
                openalex_error = exc
                continue

            openalex_root = _coerce_raw_paper(openalex_result.get("root") or {})
            if openalex_root:
                root_raw = _merge_raw_paper(root_raw, openalex_root) if root_raw else openalex_root

            openalex_ancestors = [_coerce_raw_paper(item) for item in (openalex_result.get("ancestors") or [])]
            openalex_ancestors = [item for item in openalex_ancestors if item]
            if openalex_ancestors:
                if len(ancestor_raw) < target_ancestor_count:
                    ancestor_raw = openalex_ancestors
                else:
                    ancestor_raw = _merge_raw_paper_lists(ancestor_raw, openalex_ancestors)

            openalex_descendants = [_coerce_raw_paper(item) for item in (openalex_result.get("descendants") or [])]
            openalex_descendants = [item for item in openalex_descendants if item]
            if openalex_descendants:
                if len(descendant_raw) < target_descendant_count:
                    descendant_raw = openalex_descendants
                else:
                    descendant_raw = _merge_raw_paper_lists(descendant_raw, openalex_descendants)

            if (
                root_raw
                and len(ancestor_raw) >= target_ancestor_count
                and len(descendant_raw) >= target_descendant_count
                and not _needs_metadata_enrichment(root_raw, ancestor_raw, descendant_raw)
            ):
                break

    if not root_raw:
        if isinstance(semantic_error, SemanticScholarNotFoundError):
            raise ValueError(f"paper_not_found: {safe_paper_id}") from semantic_error
        if openalex_error is not None:
            raise RuntimeError(f"openalex_error: {openalex_error}") from openalex_error
        if semantic_error is not None:
            raise RuntimeError(f"semantic_scholar_error: {semantic_error}") from semantic_error
        raise ValueError(f"paper_not_found: {safe_paper_id}")

    root_title = str(root_raw.get("title") or "").strip()
    root_abstract = str(root_raw.get("abstract") or "").strip()

    enriched_ancestors, enriched_descendants = await asyncio.gather(
        classify_citations_batch(root_title, root_abstract, ancestor_raw, direction="ancestor"),
        classify_citations_batch(root_title, root_abstract, descendant_raw, direction="descendant"),
    )

    root_node = _to_lineage_paper(root_raw, node_type="root")
    root_node.hop = 0
    root_node.generation = 0

    ancestors = [_to_lineage_paper(item, node_type="ancestor") for item in enriched_ancestors]
    descendants = [_to_lineage_paper(item, node_type="descendant") for item in enriched_descendants]

    allowed_types = set(safe_citation_types)
    ancestors = _filter_by_depth_and_type(
        ancestors,
        max_hop=safe_ancestor_depth,
        allowed_types=allowed_types,
    )
    descendants = _filter_by_depth_and_type(
        descendants,
        max_hop=safe_descendant_depth,
        allowed_types=allowed_types,
    )

    _apply_relevance(ancestors)
    _apply_relevance(descendants)

    edges = _build_edges(root_node.paper_id, ancestors, descendants)
    stats = _compute_stats(ancestors, descendants)

    response = LineageResponse(
        root=root_node,
        ancestors=ancestors,
        descendants=descendants,
        edges=edges,
        stats=stats,
        cached=False,
    )

    if ancestors or descendants:
        try:
            set_cached_lineage(
                safe_paper_id,
                ancestor_depth=safe_ancestor_depth,
                descendant_depth=safe_descendant_depth,
                citation_types=safe_citation_types,
                response=response,
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed writing lineage cache")

    # Persist enriched lineage without blocking API response.
    try:
        asyncio.create_task(
            _persist_lineage_async(
                repository,
                root_raw,
                enriched_ancestors,
                enriched_descendants,
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed scheduling lineage persistence task")

    return response
