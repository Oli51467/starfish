from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

InputType = Literal["arxiv_id", "doi", "pdf", "github_url"]
TrendLabel = Literal["rising", "stable", "saturated", "emerging"]
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
