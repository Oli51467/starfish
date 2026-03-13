from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

InputType = Literal["arxiv_id", "doi", "pdf", "github_url"]
PaperInputType = Literal["arxiv_id", "doi", "paper_id"]
TrendLabel = Literal["rising", "stable", "saturated", "emerging"]
LandscapeDirectionStatus = Literal["emerging", "growing", "stable", "saturated"]
LandscapeStepKey = Literal["research", "retrieve", "summarize", "graph"]
TaskStatus = Literal["pending", "processing", "completed", "failed"]
CitationRelationType = Literal[
    "supporting",
    "contradicting",
    "extending",
    "migrating",
    "mentioning",
]
GapType = Literal["method_scene", "stagnant", "island", "contradiction"]
GraphRole = Literal["hub", "bridge", "leaf"]
KnowledgeNodeType = Literal["paper", "entity", "domain"]
KnowledgeEdgeType = Literal["mentions", "belongs_to", "related", "covers"]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: datetime


class MapGenerateRequest(BaseModel):
    input_type: InputType
    input_value: str = Field(..., min_length=1)
    depth: int = Field(default=2, ge=1, le=4)


class TaskCreateResponse(BaseModel):
    task_id: str
    status: TaskStatus
    message: str


class TaskDetailResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: int = Field(default=0, ge=0, le=100)
    message: str = ""
    result_id: str | None = None
    error: str | None = None


class MapNode(BaseModel):
    id: str
    label: str
    paper_count: int
    trend: TrendLabel
    trend_score: float = Field(ge=0, le=1)
    top_papers: list[str] = Field(default_factory=list)


class MapEdge(BaseModel):
    source: str
    target: str
    weight: float = Field(ge=0, le=1)


class MapResponse(BaseModel):
    map_id: str
    nodes: list[MapNode] = Field(default_factory=list)
    edges: list[MapEdge] = Field(default_factory=list)
    trend_summary: str
    generated_at: datetime


class KnowledgeGraphBuildRequest(BaseModel):
    query: str = Field(..., min_length=2)
    max_papers: int = Field(default=12, ge=3, le=30)
    max_entities_per_paper: int = Field(default=6, ge=2, le=12)
    prefetched_papers: list["RetrievedPaper"] = Field(default_factory=list)


class KnowledgeGraphRetrieveRequest(BaseModel):
    query: str = Field(..., min_length=2)
    max_papers: int = Field(default=12, ge=3, le=30)


class RetrievalTraceStep(BaseModel):
    phase: Literal["search_web", "retrieve", "filter"]
    title: str
    detail: str
    status: Literal["done", "fallback"] = "done"
    provider: str = ""
    count: int = Field(default=0, ge=0)
    links: list[str] = Field(default_factory=list)
    elapsed_ms: int = Field(default=0, ge=0)


class BuildTraceStep(BaseModel):
    phase: Literal["build_extract", "store_graph"]
    title: str
    detail: str
    status: Literal["done", "fallback"] = "done"
    elapsed_ms: int = Field(default=0, ge=0)


class RetrievedPaper(BaseModel):
    paper_id: str
    title: str
    abstract: str = ""
    year: int | None = None
    month: int | None = None
    publication_date: str = ""
    citation_count: int = Field(default=0, ge=0)
    venue: str = "Unknown Venue"
    fields_of_study: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    url: str | None = None


class KnowledgeGraphRetrievalResponse(BaseModel):
    query: str
    provider: Literal["semantic_scholar", "openalex", "mock"]
    candidate_count: int = Field(default=0, ge=0)
    selected_count: int = Field(default=0, ge=0)
    papers: list[RetrievedPaper] = Field(default_factory=list)
    steps: list[RetrievalTraceStep] = Field(default_factory=list)
    generated_at: datetime


class KnowledgeGraphNode(BaseModel):
    id: str
    label: str
    type: KnowledgeNodeType
    size: float = Field(default=1.0, ge=1.0)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    paper_id: str | None = None
    meta: dict[str, str] = Field(default_factory=dict)


class KnowledgeGraphEdge(BaseModel):
    source: str
    target: str
    relation: KnowledgeEdgeType
    weight: float = Field(default=0.1, ge=0.0, le=1.0)
    meta: dict[str, str] = Field(default_factory=dict)


class KnowledgeGraphResponse(BaseModel):
    graph_id: str
    query: str
    paper_count: int = Field(ge=0)
    entity_count: int = Field(ge=0)
    domain_count: int = Field(ge=0)
    nodes: list[KnowledgeGraphNode] = Field(default_factory=list)
    edges: list[KnowledgeGraphEdge] = Field(default_factory=list)
    build_steps: list[BuildTraceStep] = Field(default_factory=list)
    stored_in_neo4j: bool = False
    summary: str
    generated_at: datetime


class LandscapeGenerateRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=120)


class LandscapeCorePaper(BaseModel):
    id: str
    title: str
    year: int | None = None
    citation_count: int = Field(default=0, ge=0)
    authors: list[str] = Field(default_factory=list)


class LandscapeSubDirection(BaseModel):
    name: str
    name_en: str = ""
    description: str = ""
    status: LandscapeDirectionStatus = "stable"
    methods: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    estimated_active_years: str = ""
    provider_used: str = ""
    paper_count: int = Field(default=0, ge=0)
    recent_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    recent_paper_count: int = Field(default=0, ge=0)
    avg_citations: int = Field(default=0, ge=0)
    correlation_score: float = Field(default=0.0, ge=0.0, le=1.0)
    core_papers: list[LandscapeCorePaper] = Field(default_factory=list)


class LandscapeResponse(BaseModel):
    landscape_id: str
    query: str
    domain_name: str
    domain_name_en: str = ""
    description: str = ""
    provider_priority: str = "openalex_then_semantic_scholar"
    sub_directions: list[LandscapeSubDirection] = Field(default_factory=list)
    trend_summary: str = ""
    summary_enabled: bool = False
    graph_data: dict[str, Any] = Field(default_factory=dict)
    stored_in_neo4j: bool = False
    generated_at: datetime


class LandscapeStepLog(BaseModel):
    timestamp: datetime
    step_key: LandscapeStepKey
    level: Literal["info", "done", "fallback", "error"] = "info"
    message: str
    meta: dict[str, str] = Field(default_factory=dict)


class LandscapeTaskDetailResponse(TaskDetailResponse):
    step_key: LandscapeStepKey = "research"
    summary_enabled: bool = False
    step_logs: list[LandscapeStepLog] = Field(default_factory=list)
    preview_graph: dict[str, Any] = Field(default_factory=dict)
    preview_stats: dict[str, Any] = Field(default_factory=dict)


class Neo4jStatusResponse(BaseModel):
    available: bool


class PaperReference(BaseModel):
    paper_id: str
    title: str
    year: int | None = None
    citation_count: int = Field(default=0, ge=0)


class PaperMetadataResponse(BaseModel):
    source: str = "semantic_scholar"
    input_type: PaperInputType
    input_value: str
    paper_id: str
    title: str
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str
    citation_count: int = Field(ge=0)
    reference_count: int = Field(ge=0)
    abstract: str
    url: str | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)
    references: list[PaperReference] = Field(default_factory=list)


class ReadingPaper(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int
    importance_score: float = Field(ge=0, le=1)
    importance_reason: str
    graph_role: GraphRole
    estimated_read_time_min: int = Field(ge=10)
    citation_count: int = Field(ge=0)
    venue: str


class ReadingLayer(BaseModel):
    layer: int
    label: str
    description: str
    papers: list[ReadingPaper] = Field(default_factory=list)


class ReadingListResponse(BaseModel):
    map_id: str
    layers: list[ReadingLayer] = Field(default_factory=list)


class GapEvidence(BaseModel):
    covered_scenarios: list[str] = Field(default_factory=list)
    uncovered_scenario: str | None = None
    paper_counts: dict[str, int] = Field(default_factory=dict)


class GapFeasibility(BaseModel):
    datasets_available: list[str] = Field(default_factory=list)
    baselines_available: list[str] = Field(default_factory=list)
    challenges: list[str] = Field(default_factory=list)


class GapItem(BaseModel):
    gap_id: str
    type: GapType
    title: str
    opportunity_score: int = Field(ge=0, le=100)
    description: str
    evidence: GapEvidence
    feasibility: GapFeasibility
    seed_papers: list[str] = Field(default_factory=list)


class GapsResponse(BaseModel):
    map_id: str
    gaps: list[GapItem] = Field(default_factory=list)
    summary: str


class PaperRef(BaseModel):
    paper_id: str
    title: str
    year: int
    citation_count: int = Field(ge=0)


class LineageNode(BaseModel):
    paper_id: str
    title: str
    year: int
    relation_type: CitationRelationType
    relation_description: str
    generation: int = Field(ge=1)
    citation_type_source: str | None = None


class LineageStats(BaseModel):
    total_descendants: int = Field(ge=0)
    supporting_ratio: float = Field(ge=0, le=1)
    contradicting_ratio: float = Field(ge=0, le=1)
    extending_ratio: float = Field(ge=0, le=1)


class LineageResponse(BaseModel):
    root_paper: PaperRef
    ancestors: list[LineageNode] = Field(default_factory=list)
    descendants: list[LineageNode] = Field(default_factory=list)
    controversy_summary: str
    lineage_stats: LineageStats
