from __future__ import annotations

from fastapi import APIRouter, HTTPException

from external.semantic_scholar import SemanticScholarClientError
from models.schemas import (
    KnowledgeGraphBuildRequest,
    KnowledgeGraphResponse,
    KnowledgeGraphRetrievalResponse,
    KnowledgeGraphRetrieveRequest,
    Neo4jStatusResponse,
)
from services.graphrag_service import get_graphrag_service

router = APIRouter(prefix="/api/graphrag", tags=["graphrag"])
graphrag_service = get_graphrag_service()


@router.post("/build", response_model=KnowledgeGraphResponse)
def build_knowledge_graph(request: KnowledgeGraphBuildRequest) -> KnowledgeGraphResponse:
    try:
        return graphrag_service.build_knowledge_graph(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SemanticScholarClientError as exc:
        raise HTTPException(status_code=502, detail=f"semantic_scholar_error: {exc}") from exc


@router.post("/retrieve", response_model=KnowledgeGraphRetrievalResponse)
def retrieve_papers(request: KnowledgeGraphRetrieveRequest) -> KnowledgeGraphRetrievalResponse:
    try:
        return graphrag_service.retrieve_papers(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SemanticScholarClientError as exc:
        raise HTTPException(status_code=502, detail=f"semantic_scholar_error: {exc}") from exc


@router.get("/neo4j/status", response_model=Neo4jStatusResponse)
def get_neo4j_status() -> Neo4jStatusResponse:
    return Neo4jStatusResponse(available=graphrag_service.get_neo4j_status())


@router.get("/{graph_id}", response_model=KnowledgeGraphResponse)
def get_knowledge_graph(graph_id: str) -> KnowledgeGraphResponse:
    try:
        return graphrag_service.fetch_knowledge_graph(graph_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
