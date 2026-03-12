from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.paper_fetcher import PaperFetcher
from external.semantic_scholar import SemanticScholarClientError, SemanticScholarNotFoundError
from models.schemas import PaperInputType, PaperMetadataResponse

router = APIRouter(prefix="/api/papers", tags=["papers"])
paper_fetcher = PaperFetcher()


@router.get("/metadata", response_model=PaperMetadataResponse)
def get_paper_metadata(
    input_type: PaperInputType = Query(default="arxiv_id"),
    input_value: str = Query(..., min_length=1),
    reference_limit: int = Query(default=20, ge=1, le=200),
) -> PaperMetadataResponse:
    normalized_value = input_value.strip()
    try:
        payload = paper_fetcher.fetch_seed_document(
            input_type=input_type,
            input_value=normalized_value,
            reference_limit=reference_limit,
        )
    except SemanticScholarNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"paper_not_found: {exc}") from exc
    except SemanticScholarClientError as exc:
        raise HTTPException(status_code=502, detail=f"semantic_scholar_error: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    seed_paper = payload.get("seed_paper", {})
    references = seed_paper.get("references") or []
    external_ids = {
        str(key): str(value)
        for key, value in (seed_paper.get("external_ids") or {}).items()
        if value is not None
    }

    return PaperMetadataResponse(
        input_type=input_type,
        input_value=normalized_value,
        paper_id=str(seed_paper.get("paper_id") or ""),
        title=seed_paper.get("title") or "",
        year=seed_paper.get("year"),
        authors=[str(item) for item in (seed_paper.get("authors") or []) if str(item).strip()],
        venue=seed_paper.get("venue") or "Unknown Venue",
        citation_count=int(seed_paper.get("citation_count") or 0),
        reference_count=int(seed_paper.get("reference_count") or len(references)),
        abstract=seed_paper.get("abstract") or "",
        url=seed_paper.get("url"),
        external_ids=external_ids,
        references=references,
    )
