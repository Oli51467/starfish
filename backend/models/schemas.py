from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

InputType = Literal["arxiv_id", "doi", "pdf", "github_url"]
ResearchType = Literal["arxiv_id", "doi", "domain", "unknown"]
PaperInputType = Literal["arxiv_id", "doi", "paper_id"]
KnowledgeGraphRetrieveInputType = Literal["domain", "arxiv_id", "doi"]
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
PaperSignalTrendLabel = Literal["rising", "steady", "cooling", "controversial"]
PaperSignalEventType = Literal[
    "lineage_expanded",
    "controversy_rise",
    "citation_delta",
    "metadata_enriched",
]
GapType = Literal["method_scene", "stagnant", "island", "contradiction"]
GraphRole = Literal["hub", "bridge", "leaf"]
KnowledgeNodeType = Literal["paper", "entity", "domain"]
KnowledgeEdgeType = Literal["mentions", "belongs_to", "related", "covers"]
SavedPaperReadStatus = Literal["unread", "reading", "completed"]
SavedPaperSortBy = Literal["saved_at", "last_opened_at", "year", "citation_count"]
SavedPaperSaveSource = Literal["manual", "auto_research"]
SortOrder = Literal["asc", "desc"]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: datetime


class AuthGoogleRequest(BaseModel):
    credential: str = Field(..., min_length=10)


class UserProfile(BaseModel):
    id: str
    email: str
    name: str = ""
    picture: str | None = None


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(ge=1)
    user: UserProfile


class ResearchHistoryLineageStatus(BaseModel):
    generated: bool = False
    ancestor_count: int = Field(default=0, ge=0)
    descendant_count: int = Field(default=0, ge=0)
    seed_paper_id: str = ""
    updated_at: datetime | None = None


class ResearchHistoryListItem(BaseModel):
    history_id: str
    research_type: ResearchType = "unknown"
    search_record: str
    search_range: str = ""
    search_time: datetime
    lineage: ResearchHistoryLineageStatus = Field(default_factory=ResearchHistoryLineageStatus)


class ResearchHistoryListResponse(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    items: list[ResearchHistoryListItem] = Field(default_factory=list)


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


PipelineInputType = Literal["arxiv_id", "doi", "domain"]
PipelineEventType = Literal[
    "node_start",
    "thinking",
    "node_complete",
    "pause",
    "graph_stream",
    "insight_stream",
    "insight_orchestrator_event",
    "negotiation_round_started",
    "negotiation_bid_received",
    "negotiation_contract_awarded",
    "negotiation_budget_update",
    "negotiation_critic_veto",
    "negotiation_rebid_scheduled",
    "session_complete",
    "error",
    "stopped",
]


class PipelineStartRequest(BaseModel):
    input_type: PipelineInputType
    input_value: str = Field(..., min_length=1, max_length=240)
    paper_range_years: int | None = Field(default=None, ge=1, le=30)
    quick_mode: bool = False


class PipelineStartResponse(BaseModel):
    session_id: str
    status: Literal["started"] = "started"


class PipelineResumeRequest(BaseModel):
    feedback: str = ""
    agent_count: int | None = Field(default=None, ge=2, le=8)
    exploration_depth: int | None = Field(default=None, ge=1, le=5)
    report_language: Literal["zh", "en"] | None = None
    agent_mode: Literal["legacy", "orchestrated"] | None = None


class PipelineResumeResponse(BaseModel):
    resumed: bool = False
    status: Literal["resumed", "no_pending_checkpoint", "session_closed"] = "resumed"


class PipelineReportResponse(BaseModel):
    session_id: str
    status: str
    progress: int = Field(default=0, ge=0, le=100)
    current_node: str = ""
    research_goal: str = ""
    report: str | None = None
    report_id: str | None = None
    errors: list[str] = Field(default_factory=list)


class PipelineStopResponse(BaseModel):
    stopped: bool = False


class ResearchSessionStartRequest(BaseModel):
    input_type: PipelineInputType
    input_value: str = Field(..., min_length=1, max_length=240)
    paper_range_years: int | None = Field(default=None, ge=1, le=30)
    quick_mode: bool = False


class ResearchSessionStartResponse(BaseModel):
    session_id: str
    status: Literal["started"] = "started"


class ResearchSessionResumeRequest(BaseModel):
    feedback: str = ""
    agent_count: int | None = Field(default=None, ge=2, le=8)
    exploration_depth: int | None = Field(default=None, ge=1, le=5)
    report_language: Literal["zh", "en"] | None = None
    agent_mode: Literal["legacy", "orchestrated"] | None = None


class ResearchSessionResumeResponse(BaseModel):
    resumed: bool = False
    status: Literal["resumed", "no_pending_checkpoint", "session_closed"] = "resumed"


class ResearchSessionStateResponse(BaseModel):
    session_id: str
    status: str
    progress: int = Field(default=0, ge=0, le=100)
    current_node: str = ""
    waiting_checkpoint: str = ""
    input_type: PipelineInputType = "arxiv_id"
    input_value: str = ""
    paper_range_years: int | None = None
    quick_mode: bool = False
    research_goal: str = ""
    execution_plan: list[str] = Field(default_factory=list)
    checkpoint_feedback: dict[str, str] = Field(default_factory=dict)
    graph: dict[str, Any] | None = None
    lineage: dict[str, Any] | None = None
    report: str | None = None
    report_id: str | None = None
    insight: dict[str, Any] | None = None
    history_id: str | None = None
    research_gaps: list[dict[str, Any]] = Field(default_factory=list)
    critic_notes: list[str] = Field(default_factory=list)
    papers: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)


class ResearchSessionStopResponse(BaseModel):
    stopped: bool = False


class ResearchActiveSessionSummary(BaseModel):
    session_id: str
    status: str
    progress: int = Field(default=0, ge=0, le=100)
    current_node: str = ""
    waiting_checkpoint: str = ""
    input_type: PipelineInputType = "arxiv_id"
    input_value: str = ""
    paper_range_years: int | None = None
    quick_mode: bool = False
    updated_at: str = ""


class ResearchActiveSessionResponse(BaseModel):
    has_active_session: bool = False
    session: ResearchActiveSessionSummary | None = None


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
    max_papers: int = Field(default=24, ge=3, le=30)
    max_entities_per_paper: int = Field(default=6, ge=2, le=12)
    prefetched_papers: list["RetrievedPaper"] = Field(default_factory=list)
    research_type: ResearchType = "unknown"
    search_input: str = ""
    search_range: str = ""


class KnowledgeGraphRetrieveRequest(BaseModel):
    query: str = Field(..., min_length=2)
    max_papers: int = Field(default=24, ge=3, le=30)
    input_type: KnowledgeGraphRetrieveInputType = "domain"
    quick_mode: bool = False
    paper_range_years: int | None = Field(default=None, ge=1, le=30)


class RetrievalTraceStep(BaseModel):
    phase: Literal["search_web", "retrieve", "filter"]
    title: str
    detail: str
    status: Literal["done", "fallback"] = "done"
    provider: str = ""
    count: int = Field(default=0, ge=0)
    links: list[str] = Field(default_factory=list)
    elapsed_ms: int = Field(default=0, ge=0)


class RetrievalProviderStat(BaseModel):
    provider: str
    status: Literal["done", "fallback"] = "done"
    count: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)
    error: str = ""


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
    provider: Literal["semantic_scholar", "openalex", "crossref", "arxiv", "mock"]
    providers_used: list[str] = Field(default_factory=list)
    provider_stats: list[RetrievalProviderStat] = Field(default_factory=list)
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


class ResearchHistoryDetailResponse(BaseModel):
    history_id: str
    research_type: ResearchType = "unknown"
    search_record: str
    search_range: str = ""
    search_time: datetime
    lineage: ResearchHistoryLineageStatus = Field(default_factory=ResearchHistoryLineageStatus)
    graph: KnowledgeGraphResponse
    landscape_graph: dict[str, Any] | None = None
    lineage_graph: dict[str, Any] | None = None
    pipeline: dict[str, Any] | None = None


class ResearchHistoryLineageUpdateRequest(BaseModel):
    graph_id: str = Field(..., min_length=1)
    seed_paper_id: str = Field(..., min_length=1)
    ancestor_count: int = Field(default=0, ge=0)
    descendant_count: int = Field(default=0, ge=0)
    lineage_payload: dict[str, Any] | None = None


class ResearchHistoryLineageUpdateResponse(BaseModel):
    updated: bool = False


class ResearchHistoryDeleteResponse(BaseModel):
    deleted: bool = False


class ResearchHistoryBatchDeleteRequest(BaseModel):
    history_ids: list[str] = Field(default_factory=list, min_length=1, max_length=100)


class ResearchHistoryBatchDeleteResponse(BaseModel):
    deleted: bool = False
    deleted_count: int = Field(default=0, ge=0)
    deleted_ids: list[str] = Field(default_factory=list)


class ResearchHistoryReportRegenerateResponse(BaseModel):
    history_id: str
    regenerated: bool = False
    pdf_path: str = ""


class PaperSignal(BaseModel):
    paper_id: str
    paper_title: str = ""
    citation_count: int = Field(default=0, ge=0)
    published_year: int | None = None
    ancestor_count: int = Field(default=0, ge=0)
    descendant_count: int = Field(default=0, ge=0)
    relation_distribution: dict[str, int] = Field(default_factory=dict)
    heat_score: float = Field(default=0.0, ge=0.0, le=1.0)
    controversy_score: float = Field(default=0.0, ge=0.0, le=1.0)
    trend_label: PaperSignalTrendLabel = "steady"
    computed_at: datetime


class PaperSignalRefreshRequest(BaseModel):
    collection_id: str = ""
    limit: int = Field(default=20, ge=1, le=50)
    force_refresh: bool = False


class PaperSignalRefreshItem(BaseModel):
    saved_paper_id: str
    paper_id: str
    signal: PaperSignal
    event_created: bool = False


class PaperSignalRefreshResponse(BaseModel):
    refreshed_count: int = Field(default=0, ge=0)
    event_count: int = Field(default=0, ge=0)
    items: list[PaperSignalRefreshItem] = Field(default_factory=list)


class PaperSignalEvent(BaseModel):
    event_id: str
    saved_paper_id: str
    paper_id: str
    event_type: PaperSignalEventType
    title: str
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)
    is_read: bool = False
    created_at: datetime


class PaperSignalEventListResponse(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    unread_count: int = Field(ge=0)
    items: list[PaperSignalEvent] = Field(default_factory=list)


class PaperSignalEventReadResponse(BaseModel):
    updated: bool = False


class CollectionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="", max_length=20)
    emoji: str = Field(default="", max_length=10)


class CollectionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=20)
    emoji: str | None = Field(default=None, max_length=10)


class CollectionItem(BaseModel):
    collection_id: str
    name: str
    color: str = ""
    emoji: str = ""
    paper_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class CollectionListResponse(BaseModel):
    items: list[CollectionItem] = Field(default_factory=list)


class SavedPaperMetadata(BaseModel):
    title: str = ""
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    publication_date: str = ""
    citation_count: int = Field(default=0, ge=0)
    impact_factor: float | None = Field(default=None, ge=0)
    fields_of_study: list[str] = Field(default_factory=list)
    venue: str = ""
    url: str | None = None


class SavedPaperCreateRequest(BaseModel):
    paper_id: str = Field(..., min_length=1, max_length=200)
    collection_ids: list[str] = Field(default_factory=list, max_length=20)
    metadata: SavedPaperMetadata | None = None
    save_source: SavedPaperSaveSource | None = None


class SavedPaperStatusUpdateRequest(BaseModel):
    read_status: SavedPaperReadStatus
    touch_last_opened: bool = True


class CollectionPaperAttachRequest(BaseModel):
    saved_paper_id: str = Field(..., min_length=1)


class SavedPaperItem(BaseModel):
    saved_paper_id: str
    paper_id: str
    read_status: SavedPaperReadStatus
    saved_at: datetime
    last_opened_at: datetime | None = None
    collection_ids: list[str] = Field(default_factory=list)
    metadata: SavedPaperMetadata = Field(default_factory=SavedPaperMetadata)


class SavedPaperListResponse(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    items: list[SavedPaperItem] = Field(default_factory=list)


class CollectionDeleteResponse(BaseModel):
    deleted: bool = False


class CollectionAutoCleanupResponse(BaseModel):
    cleaned: bool = False
    deleted_collections: int = Field(default=0, ge=0)
    deleted_papers: int = Field(default=0, ge=0)
    deleted_notes: int = Field(default=0, ge=0)


class SavedPaperDeleteResponse(BaseModel):
    deleted: bool = False


class SavedPaperNoteCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)


class SavedPaperNoteItem(BaseModel):
    note_id: str
    saved_paper_id: str
    content: str
    created_at: datetime
    updated_at: datetime


class SavedPaperNoteListResponse(BaseModel):
    items: list[SavedPaperNoteItem] = Field(default_factory=list)


class SavedPaperNoteDeleteResponse(BaseModel):
    deleted: bool = False


class CollectionPaperAttachResponse(BaseModel):
    linked: bool = False


class CollectionPaperDetachResponse(BaseModel):
    unlinked: bool = False


class LandscapeGenerateRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=120)
    paper_range_years: int | None = Field(default=None, ge=1, le=30)
    quick_mode: bool = False


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


LineageNodeType = Literal["root", "ancestor", "descendant"]


class LineagePaper(BaseModel):
    id: str
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    publication_date: str | None = None
    citation_count: int = Field(default=0, ge=0)
    venue: str | None = None
    abstract: str | None = None
    arxiv_id: str | None = None
    node_type: LineageNodeType
    ctype: CitationRelationType | None = None
    relevance: float | None = Field(default=None, ge=0, le=1)
    hop: int = Field(default=1, ge=0)

    # Backward-compatible fields for legacy frontend consumers.
    relation_type: CitationRelationType | None = None
    relation_description: str = ""
    generation: int = Field(default=1, ge=0)


class LineageEdge(BaseModel):
    source: str
    target: str
    ctype: CitationRelationType
    hop: int = Field(default=1, ge=1)


class LineageStats(BaseModel):
    total_ancestors: int = Field(default=0, ge=0)
    total_descendants: int = Field(default=0, ge=0)
    type_distribution: dict[str, int] = Field(default_factory=dict)
    has_controversy: bool = False
    controversy_count: int = Field(default=0, ge=0)
    year_range: tuple[int, int] = (0, 0)


class LineageResponse(BaseModel):
    root: LineagePaper
    ancestors: list[LineagePaper] = Field(default_factory=list)
    descendants: list[LineagePaper] = Field(default_factory=list)
    edges: list[LineageEdge] = Field(default_factory=list)
    stats: LineageStats = Field(default_factory=LineageStats)
    cached: bool = False
