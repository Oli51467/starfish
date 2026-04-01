import { computed, onUnmounted, ref } from 'vue';

import {
  buildKnowledgeGraph,
  createResearchWebSocket,
  downloadResearchReport,
  getActiveResearchSession,
  getKnowledgeGraph,
  getResearchSession,
  retrieveKnowledgePapers,
  resumeResearchSession,
  startResearchSession,
  stopResearchSession,
} from '../api';
import { buildKnowledgeGraphSets } from '../components/graph/knowledgeGraphModel';
import { locale as runtimeLocale } from '../i18n/runtime';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toStatusText(status) {
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'doing' || normalized === 'running') return '进行中';
  if (normalized === 'done') return '已完成';
  if (normalized === 'pending' || normalized === 'action_required') return '准备中';
  if (normalized === 'fallback' || normalized === 'failed' || normalized === 'error') return '失败';
  return '准备中';
}

function resolveRetrievalCopyMap(inputType) {
  if (inputType === 'arxiv_id' || inputType === 'doi') {
    return {
      search_web: { title: 'Planner Agent', detail: '已确认目标论文与研究边界。' },
      retrieve: { title: 'Retriever Agent', detail: '已扩展目标论文的引用与被引关系。' },
      filter: { title: 'Critic Agent', detail: '已完成相关性与证据强度筛选。' }
    };
  }
  return {
    search_web: { title: 'Planner Agent', detail: '已完成研究范围与关键词确认。' },
    retrieve: { title: 'Retriever Agent', detail: '已补充候选论文集合。' },
    filter: { title: 'Critic Agent', detail: '已完成相关性与证据强度筛选。' }
  };
}

function normalizeTraceStep(step, inputType = 'domain') {
  const phase = String(step?.phase || '').trim().toLowerCase();
  const status = String(step?.status || '').toLowerCase() === 'fallback' ? 'fallback' : 'done';
  const count = Number(step?.count);
  const phaseCopy = resolveRetrievalCopyMap(inputType)[phase] || resolveRetrievalCopyMap(inputType).filter;
  const detail = status === 'fallback'
    ? '该阶段遇到波动，已自动切换备用路径继续。'
    : (
      Number.isFinite(count) && count > 0 && phase !== 'search_web'
        ? `已处理 ${Math.round(count)} 条相关信息。`
        : phaseCopy.detail
    );
  return {
    title: phaseCopy.title,
    detail,
    status,
    statusText: toStatusText(status),
    metaText: ''
  };
}

function normalizeBuildTraceStep(step) {
  const phase = String(step?.phase || '').trim().toLowerCase();
  const status = String(step?.status || '').toLowerCase() === 'fallback' ? 'fallback' : 'done';
  if (phase === 'store_graph') {
    return {
      title: 'Verifier Agent',
      detail: status === 'fallback' ? '图谱保存阶段出现波动，已保留当前结果。' : '图谱结构已整理完成。',
      status,
      statusText: toStatusText(status),
      metaText: ''
    };
  }
  return {
    title: 'Graph Builder Agent',
    detail: status === 'fallback' ? '关系整理阶段出现波动，已继续后续流程。' : '论文与主题关系已完成整理。',
    status,
    statusText: toStatusText(status),
    metaText: ''
  };
}

function parsePaperRangeYears(rawValue) {
  const parsed = Number(rawValue);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.min(30, Math.round(parsed));
}

function formatSearchRangeLabel(inputType, paperRangeYears) {
  if (String(inputType || '').trim().toLowerCase() === 'domain') {
    if (Number.isFinite(Number(paperRangeYears)) && Number(paperRangeYears) > 0) {
      return `近 ${Math.round(Number(paperRangeYears))} 年`;
    }
    return '所有时间';
  }
  return '-';
}

function createRetrievalRunningMessage(inputType) {
  if (inputType === 'arxiv_id' || inputType === 'doi') return '正在围绕目标论文扩展相关研究...';
  return '正在检索该方向的代表性论文...';
}

function createRunningRetrievalLogs(inputType) {
  const sourceDetail = inputType === 'domain'
    ? '正在拆解研究目标并生成检索关键词...'
    : '正在定位目标论文并规划扩展检索路径...';
  return [
    {
      title: 'Planner Agent',
      detail: sourceDetail,
      status: 'doing',
      statusText: toStatusText('doing'),
      metaText: ''
    },
    {
      title: 'Retriever Agent',
      detail: '正在并行拉取多源候选论文...',
      status: 'doing',
      statusText: toStatusText('doing'),
      metaText: ''
    },
    {
      title: 'Critic Agent',
      detail: '等待候选结果返回后启动证据审查。',
      status: 'pending',
      statusText: toStatusText('pending'),
      metaText: ''
    }
  ];
}

function createFallbackRetrievalLogs(retrieval) {
  const selectedCount = Number(retrieval?.selected_count || 0);
  const candidateCount = Number(retrieval?.candidate_count || 0);
  return [
    {
      title: 'Retriever Agent',
      detail: '候选论文收集已完成。',
      status: 'done',
      statusText: toStatusText('done'),
      metaText: ''
    },
    {
      title: 'Critic Agent',
      detail: `已从 ${candidateCount} 个候选中筛选 ${selectedCount} 篇论文。`,
      status: 'done',
      statusText: toStatusText('done'),
      metaText: ''
    }
  ];
}

function normalizeProviderLabel(providerName) {
  const normalized = String(providerName || '').trim().toLowerCase();
  if (normalized === 'openalex') return 'Retriever SubAgent · OpenAlex';
  if (normalized === 'semantic_scholar') return 'Retriever SubAgent · Semantic Scholar';
  if (normalized === 'arxiv') return 'Retriever SubAgent · arXiv';
  return `Retriever SubAgent · ${providerName || 'Unknown'}`;
}

function createRetrievalAuditLogs(retrieval) {
  const logs = [];
  const providerStats = Array.isArray(retrieval?.provider_stats) ? retrieval.provider_stats : [];
  for (const item of providerStats) {
    const count = Number(item?.count || 0);
    const statusRaw = String(item?.status || '').trim().toLowerCase();
    const isFallback = statusRaw === 'fallback';
    logs.push({
      title: normalizeProviderLabel(item?.provider),
      detail: isFallback
        ? '该检索子通道出现波动，已自动降级。'
        : `该检索子通道完成候选收集（${count} 条）。`,
      status: isFallback ? 'fallback' : 'done',
      statusText: toStatusText(isFallback ? 'fallback' : 'done'),
      metaText: ''
    });
  }

  const papers = Array.isArray(retrieval?.papers) ? retrieval.papers : [];
  if (papers.length) {
    const years = papers
      .map((item) => Number(item?.year || 0))
      .filter((value) => Number.isFinite(value) && value > 0);
    const span = years.length ? Math.max(...years) - Math.min(...years) : 0;
    logs.push({
      title: 'Quality SubAgent',
      detail: span >= 5
        ? `时间覆盖较完整（跨度 ${span} 年），可继续建图。`
        : `时间覆盖偏窄（跨度 ${span} 年），后续将补充对照证据。`,
      status: span >= 5 ? 'done' : 'fallback',
      statusText: toStatusText(span >= 5 ? 'done' : 'fallback'),
      metaText: ''
    });
  }

  return logs;
}

function createRunningBuildLogs() {
  return [
    {
      title: 'Graph Builder Agent',
      detail: '正在整理论文之间的关联结构...',
      status: 'doing',
      statusText: toStatusText('doing'),
      metaText: ''
    },
    {
      title: 'Verifier Agent',
      detail: '等待结构整理完成后生成图谱。',
      status: 'pending',
      statusText: toStatusText('pending'),
      metaText: ''
    }
  ];
}

function createFallbackBuildLogs(result) {
  const paperCount = Number(result?.paper_count || 0);
  const entityCount = Number(result?.entity_count || 0);
  return [
    {
      title: 'Graph Builder Agent',
      detail: '已完成论文关系整理。',
      status: 'done',
      statusText: toStatusText('done'),
      metaText: ''
    },
    {
      title: 'Verifier Agent',
      detail: `已构建图谱内容（论文 ${paperCount}，主题 ${entityCount}）。`,
      status: 'done',
      statusText: toStatusText('done'),
      metaText: ''
    }
  ];
}

function resolveReportLanguageFromLocale() {
  return String(runtimeLocale.value || '').trim().toLowerCase() === 'en' ? 'en' : 'zh';
}

function toNodeId(raw, fallback) {
  const value = String(raw || '').trim();
  if (!value) return fallback;
  const sanitized = value.replace(/\s+/g, '-').replace(/[^\w:.-]/g, '');
  return sanitized || fallback;
}

function buildRetrievalPreviewGraph(query, papers) {
  const safeQuery = String(query || '').trim();
  const sourcePapers = Array.isArray(papers) ? papers : [];
  const topPapers = sourcePapers.slice(0, 12);
  const maxCitation = Math.max(1, ...topPapers.map((paper) => Number(paper?.citation_count || 0)));

  const nodes = topPapers
    .map((paper, index) => {
      const title = String(paper?.title || '').trim();
      if (!title) return null;
      const citationCount = Number(paper?.citation_count || 0);
      const citationRate = Math.min(citationCount / maxCitation, 1);
      const rankRate = 1 - index / Math.max(1, topPapers.length);
      const relevance = Math.max(0.12, Math.min(0.22 + citationRate * 0.56 + rankRate * 0.22, 1));
      const tier = index < 3 ? 1 : (index < 8 ? 2 : 3);
      const importanceScore = Math.max(0, Math.min(100, (citationRate * 0.62 + rankRate * 0.38) * 100));
      const tierBaseSize = tier === 1 ? 48 : (tier === 2 ? 34 : 22);
      const nodeSize = Math.max(18, Math.min(62, tierBaseSize + importanceScore * 0.06));
      const paperId = toNodeId(paper?.paper_id, `preview-${index}`);
      return {
        id: `paper:${paperId}`,
        label: title,
        type: 'paper',
        score: Number((importanceScore / 100).toFixed(3)),
        size: Number(nodeSize.toFixed(2)),
        tier,
        importance_score: Number(importanceScore.toFixed(1)),
        meta: {
          title,
          abstract: String(paper?.abstract || ''),
          year: String(paper?.year || ''),
          published_month: String(paper?.month || ''),
          citation_count: String(citationCount),
          venue: String(paper?.venue || ''),
          authors: Array.isArray(paper?.authors) ? paper.authors.join(', ') : '',
          url: String(paper?.url || ''),
          relevance: relevance.toFixed(3),
          importance_score: importanceScore.toFixed(1),
          tier: String(tier),
          node_size: nodeSize.toFixed(1),
          node_color_weight: Math.max(0.2, Math.min(1, importanceScore / 100)).toFixed(3),
          internal_citations: '0'
        }
      };
    })
    .filter(Boolean);

  const edges = [];
  for (let index = 0; index < nodes.length - 1; index += 1) {
    edges.push({
      source: nodes[index].id,
      target: nodes[index + 1].id,
      relation: 'related',
      weight: 0.36
    });
  }

  const leadPaper = nodes[0];
  const leadTitle = String(leadPaper?.label || '').trim();
  const summary = leadTitle
    ? `先导结果：核心论文候选《${leadTitle}》，已快速召回 ${nodes.length} 篇相关论文。`
    : `先导结果：已快速召回 ${nodes.length} 篇相关论文。`;

  return {
    query: safeQuery,
    title: `${safeQuery} 实时图谱预览`,
    summary,
    nodes,
    edges,
    aha: {
      summary
    }
  };
}

function extractPanoramaStats(rawGraph) {
  const graphSets = buildKnowledgeGraphSets(rawGraph || {});
  const panorama = graphSets.panorama || {};
  const nodes = Array.isArray(panorama?.nodes) ? panorama.nodes : [];
  const edges = Array.isArray(panorama?.edges) ? panorama.edges : [];
  const paperCount = nodes.filter((node) => String(node?.kind || node?.type || '').toLowerCase() === 'paper').length;
  return {
    nodeCount: nodes.length,
    edgeCount: edges.length,
    paperCount
  };
}

const RESEARCH_NODE_LABEL = {
  planner: 'Planner Agent',
  router: 'Router Agent',
  search: 'Retriever Agent',
  graph_build: 'Graph Builder Agent',
  checkpoint_1: 'Human Checkpoint',
  checkpoint_2: 'Insight Checkpoint',
  insight: 'Insight Agent'
};

const NEGOTIATION_PROFILE_LABEL = {
  precise: '精确策略',
  fast: '快速策略',
  budget: '预算优先',
  recall: '覆盖优先',
  dense: '深度建模',
  balanced: '平衡策略',
  guarded: '稳健策略',
  quickpass: '快速确认',
  lean: '轻量策略',
  stable: '稳定策略',
  breadth: '广覆盖策略'
};

const STEP_FLOW_ORDER = ['retrieve', 'checkpoint', 'graph', 'insight'];
const STEP_FINAL_NODE = {
  retrieve: 'search',
  checkpoint: 'checkpoint_1',
  graph: 'graph_build',
  insight: 'insight'
};

const INSIGHT_AGENT_COUNT_DEFAULT = 4;
const INSIGHT_DEPTH_DEFAULT = 2;
const INSIGHT_AGENT_COUNT_MIN = 2;
const INSIGHT_AGENT_COUNT_MAX = 8;
const INSIGHT_DEPTH_MIN = 1;
const INSIGHT_DEPTH_MAX = 5;
const INSIGHT_AGENT_COUNT_OPTIONS = Array.from(
  { length: INSIGHT_AGENT_COUNT_MAX - INSIGHT_AGENT_COUNT_MIN + 1 },
  (_, index) => {
    const value = INSIGHT_AGENT_COUNT_MIN + index;
    return {
      label: String(value),
      value: String(value)
    };
  }
);
const INSIGHT_DEPTH_OPTIONS = Array.from(
  { length: INSIGHT_DEPTH_MAX - INSIGHT_DEPTH_MIN + 1 },
  (_, index) => {
    const value = INSIGHT_DEPTH_MIN + index;
    return {
      label: String(value),
      value: String(value)
    };
  }
);

const ACTIVE_RESEARCH_SESSION_STORAGE_KEY = 'starfish:active-research-session';
const COMPLETED_WORKFLOW_SNAPSHOT_STORAGE_KEY = 'starfish:workflow-completed-snapshot';
const INSIGHT_STREAM_STALL_MS = 15000;
const INSIGHT_STREAM_WATCHDOG_INTERVAL_MS = 2000;
const RUNTIME_EVENT_CLOCK_SKEW_MS = 1200;

function safeJsonClone(value, fallback = null) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return fallback;
  }
}

function buildWorkflowSeedFingerprint(seed = {}) {
  const inputType = String(seed?.input_type || 'domain').trim().toLowerCase();
  const inputValue = String(seed?.input_value || '').trim().toLowerCase();
  const rangeYears = parsePaperRangeYears(seed?.paper_range_years);
  const rangeKey = rangeYears ? String(rangeYears) : 'all';
  const quickMode = seed?.quick_mode === undefined ? true : Boolean(seed.quick_mode);
  return `${inputType}|${inputValue}|${rangeKey}|q${quickMode ? 1 : 0}`;
}

function readCompletedWorkflowSnapshot() {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(COMPLETED_WORKFLOW_SNAPSHOT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

function writeCompletedWorkflowSnapshot(payload = {}) {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(COMPLETED_WORKFLOW_SNAPSHOT_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // ignore storage write failures
  }
}

function clearCompletedWorkflowSnapshot() {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(COMPLETED_WORKFLOW_SNAPSHOT_STORAGE_KEY);
  } catch {
    // ignore storage remove failures
  }
}

function persistActiveResearchSessionRecord(payload = {}) {
  if (typeof window === 'undefined') return;
  const sessionId = String(payload?.session_id || '').trim();
  if (!sessionId) return;

  const record = {
    session_id: sessionId,
    status: String(payload?.status || '').trim().toLowerCase(),
    progress: Number.isFinite(Number(payload?.progress)) ? Number(payload.progress) : 0,
    current_node: String(payload?.current_node || '').trim(),
    waiting_checkpoint: String(payload?.waiting_checkpoint || '').trim(),
    input_type: String(payload?.input_type || 'domain').trim().toLowerCase(),
    input_value: String(payload?.input_value || '').trim(),
    paper_range_years: Number.isFinite(Number(payload?.paper_range_years))
      ? Math.max(1, Math.round(Number(payload.paper_range_years)))
      : null,
    quick_mode: Boolean(payload?.quick_mode),
    updated_at: String(payload?.updated_at || new Date().toISOString()).trim() || new Date().toISOString()
  };

  try {
    window.localStorage.setItem(ACTIVE_RESEARCH_SESSION_STORAGE_KEY, JSON.stringify(record));
  } catch {
    // ignore storage write failures
  }
}

function clearActiveResearchSessionRecord() {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(ACTIVE_RESEARCH_SESSION_STORAGE_KEY);
  } catch {
    // ignore storage remove failures
  }
}

function createNegotiationBudgetState() {
  return {
    spent: null,
    limit: null,
    remaining: null
  };
}

function createNegotiationRoundState({
  round = 1,
  taskId = '',
  taskKind = '',
  status = 'bidding',
  updatedAt = ''
} = {}) {
  return {
    round,
    taskId,
    taskKind,
    status,
    bids: [],
    winner: null,
    veto: null,
    rebid: null,
    updatedAt
  };
}

function createNegotiationStepState() {
  return {
    activeTaskKind: '',
    activeRound: 0,
    budget: createNegotiationBudgetState(),
    rounds: []
  };
}

function createNegotiationStateByStep() {
  return {
    retrieve: createNegotiationStepState(),
    checkpoint: createNegotiationStepState(),
    graph: createNegotiationStepState(),
    insight: createNegotiationStepState()
  };
}

function resolveStepKeyByNode(rawNode) {
  const node = String(rawNode || '').trim().toLowerCase();
  if (!node) return 'retrieve';
  if (node === 'planner' || node === 'router' || node === 'search') return 'retrieve';
  if (node === 'checkpoint_1') return 'checkpoint';
  if (node === 'checkpoint_2' || node === 'insight') return 'insight';
  if (node === 'graph_build' || node === 'synthesizer' || node === 'report' || node === 'save') return 'graph';
  return 'retrieve';
}

function resolveStepKeyByTaskKind(rawTaskKind) {
  const taskKind = String(rawTaskKind || '').trim().toLowerCase();
  if (!taskKind) return 'retrieve';
  if (taskKind === 'checkpoint_1') return 'checkpoint';
  if (taskKind === 'checkpoint_2' || taskKind === 'insight') return 'insight';
  if (taskKind === 'graph_build') return 'graph';
  if (taskKind === 'planner' || taskKind === 'router' || taskKind === 'search') return 'retrieve';
  return 'retrieve';
}

function resolveNodeLabel(rawNode) {
  const node = String(rawNode || '').trim().toLowerCase();
  return RESEARCH_NODE_LABEL[node] || `Agent · ${node || 'unknown'}`;
}

function resolveTaskKindLabel(rawTaskKind) {
  const taskKind = String(rawTaskKind || '').trim().toLowerCase();
  return resolveNodeLabel(taskKind || 'planner');
}

function normalizeRuntimeSeed(seed = {}) {
  return {
    input_type: String(seed?.input_type || 'domain').trim().toLowerCase() === 'domain'
      ? 'domain'
      : (String(seed?.input_type || '').trim().toLowerCase() === 'doi' ? 'doi' : 'arxiv_id'),
    input_value: String(seed?.input_value || '').trim(),
    paper_range_years: parsePaperRangeYears(seed?.paper_range_years),
    quick_mode: Boolean(seed?.quick_mode),
    runtime_session_id: String(seed?.runtime_session_id || '').trim()
  };
}

function normalizeRuntimeSeedFromActiveSession(activeSession = {}, fallbackSeed = {}) {
  const normalizedFallback = normalizeRuntimeSeed(fallbackSeed || {});
  const sessionId = String(activeSession?.session_id || '').trim();
  if (!sessionId) return null;

  const inputTypeRaw = String(activeSession?.input_type || normalizedFallback.input_type || 'domain').trim().toLowerCase();
  const inputType = inputTypeRaw === 'domain'
    ? 'domain'
    : (inputTypeRaw === 'doi' ? 'doi' : 'arxiv_id');
  const inputValue = String(
    activeSession?.input_value !== undefined
      ? activeSession.input_value
      : normalizedFallback.input_value
  ).trim();
  const quickMode = activeSession?.quick_mode !== undefined
    ? Boolean(activeSession.quick_mode)
    : Boolean(normalizedFallback.quick_mode);
  const paperRangeYears = parsePaperRangeYears(
    activeSession?.paper_range_years !== undefined
      ? activeSession.paper_range_years
      : normalizedFallback.paper_range_years
  );

  return normalizeRuntimeSeed({
    input_type: inputType,
    input_value: inputValue,
    paper_range_years: paperRangeYears,
    quick_mode: quickMode,
    runtime_session_id: sessionId
  });
}

function toFiniteNegotiationNumber(rawValue) {
  if (rawValue === null || rawValue === undefined) return null;
  if (typeof rawValue === 'string' && !rawValue.trim()) return null;
  const parsed = Number(rawValue);
  return Number.isFinite(parsed) ? parsed : null;
}

function hasNegotiationMetricValue(rawValue) {
  const parsed = toFiniteNegotiationNumber(rawValue);
  return Number.isFinite(parsed) && parsed > 0;
}

function shouldFallbackToLegacy(error) {
  const message = String(error?.message || '').trim().toLowerCase();
  if (!message) return false;
  if (message.includes('403') || message.includes('401') || message.includes('forbidden')) return false;
  return (
    message.includes('404')
    || message.includes('session_not_found')
    || message.includes('/api/research')
    || message.includes('not found')
    || message.includes('connection')
  );
}

export function usePaperWorkflow({
  seedRef,
  accessTokenRef,
  onStepChange
}) {
  const notifyStepChange = typeof onStepChange === 'function' ? onStepChange : () => {};

  const steps = ref([
    {
      index: 1,
      key: 'retrieve',
      title: '论文检索',
      description: '围绕输入主题收集并筛选高相关论文。',
      status: 'pending',
      message: '',
      logs: []
    },
    {
      index: 2,
      key: 'checkpoint',
      title: '需求确认',
      description: '检索结果确认后自动继续生成知识图谱。',
      status: 'pending',
      message: '',
      logs: [],
      action: null
    },
    {
      index: 3,
      key: 'graph',
      title: '生成知识图谱',
      description: '将论文关系组织成可交互知识图谱。',
      status: 'pending',
      message: '',
      logs: []
    },
    {
      index: 4,
      key: 'insight',
      title: '探索与洞察',
      description: '多智能体自主探索并生成可执行洞察报告。',
      status: 'pending',
      message: '',
      logs: [],
      action: null
    }
  ]);

  const graphLoading = ref(false);
  const terminatingWorkflow = ref(false);
  const graphData = ref(null);
  const insightReportMarkdown = ref('');
  const insightReportLanguage = ref('zh');
  const insightReportReady = ref(false);
  const insightReportStreaming = ref(false);
  const insightStreamAccumulatedChars = ref(0);
  const lastInsightStreamAt = ref(0);
  const insightMarkdownDownloadLoading = ref(false);
  const insightPdfDownloadLoading = ref(false);
  const errorMessage = ref('');
  const researchSessionId = ref('');
  const unifiedRuntimeActive = ref(false);
  const waitingResearchCheckpoint = ref('');
  const runtimeAutoResumingCheckpoint = ref('');
  const graphSnapshotSignature = ref('');
  const runtimeSeed = ref(normalizeRuntimeSeed({}));
  const negotiationByStep = ref(createNegotiationStateByStep());
  const insightAgentCountDraft = ref(String(INSIGHT_AGENT_COUNT_DEFAULT));
  const insightDepthDraft = ref(String(INSIGHT_DEPTH_DEFAULT));
  const insightConfigSubmitting = ref(false);

  let researchSocket = null;
  let researchPollTimer = null;
  let insightStreamWatchdogTimer = null;
  let insightStreamReconcileInFlight = false;
  let runtimeLastEventTsMs = 0;
  const runtimeNodeLogCursor = new Map();
  const graphStreamCursor = new Set();

  const graphStats = computed(() => {
    const stats = extractPanoramaStats(graphData.value || {});
    return {
      nodeCount: stats.nodeCount,
      edgeCount: stats.edgeCount,
      directionCount: 0
    };
  });

  const hasInsightReport = computed(() => {
    return Boolean(String(insightReportMarkdown.value || '').trim());
  });

  const insightReportPlaceholderText = computed(() => {
    if (insightReportStreaming.value) {
      return '正在实时生成报告内容...';
    }
    const insightStep = steps.value.find((item) => item.key === 'insight');
    const insightMessage = String(insightStep?.message || '').trim();
    const insightStatus = String(insightStep?.status || '').trim().toLowerCase();
    if (insightMessage && (insightStatus === 'running' || insightStatus === 'action_required')) {
      return insightMessage;
    }
    return '图谱完成并确认参数后，将在此处显示探索报告。';
  });

  const insightInlineConfig = computed(() => ({
    agentCount: String(insightAgentCountDraft.value || ''),
    explorationDepth: String(insightDepthDraft.value || ''),
    agentCountOptions: INSIGHT_AGENT_COUNT_OPTIONS,
    explorationDepthOptions: INSIGHT_DEPTH_OPTIONS,
    submitting: Boolean(insightConfigSubmitting.value)
  }));

  const activeStep = computed(() => {
    const running = steps.value.find((item) => item.status === 'running');
    if (running) return running;

    const failed = steps.value.find((item) => item.status === 'failed');
    if (failed) return failed;

    const actionRequired = steps.value.find((item) => item.status === 'action_required');
    if (actionRequired) return actionRequired;

    const done = [...steps.value].reverse().find((item) => ['done', 'skipped'].includes(item.status));
    return done || steps.value[0];
  });

  const workflowProgress = computed(() => {
    const total = Math.max(1, steps.value.length);
    const doneCount = steps.value.filter((item) => ['done', 'skipped'].includes(String(item.status || '').toLowerCase())).length;
    const hasRunning = steps.value.some((item) => String(item.status || '').toLowerCase() === 'running');
    const hasActionRequired = steps.value.some((item) => String(item.status || '').toLowerCase() === 'action_required');
    const partial = hasRunning || hasActionRequired ? 0.5 : 0;
    const percent = Math.round(((doneCount + partial) / total) * 100);
    return Math.max(0, Math.min(100, percent));
  });

  const canTerminateWorkflow = computed(() => (
    Boolean(unifiedRuntimeActive.value)
    || Boolean(graphLoading.value)
  ));

  const activeStepHint = computed(() => {
    const current = activeStep.value;
    if (!current) return '工作流运行中...';
    if (current.message) return current.message;
    const latestLog = Array.isArray(current.logs) ? current.logs.at(-1) : null;
    if (latestLog?.detail) return latestLog.detail;
    return current.description || '工作流运行中...';
  });

  const currentTaskText = computed(() => activeStepHint.value);

  const nextTaskText = computed(() => {
    const current = activeStep.value;
    if (!current) return '等待下一步执行。';
    const status = String(current.status || '').toLowerCase();
    if (status === 'action_required') {
      if (String(current.key || '').trim() === 'insight') {
        return '配置探索参数后将启动探索与洞察。';
      }
      return '确认后将继续生成知识图谱。';
    }

    const currentIndex = steps.value.findIndex((item) => item.index === current.index);
    for (let index = currentIndex + 1; index < steps.value.length; index += 1) {
      const item = steps.value[index];
      const itemStatus = String(item.status || '').toLowerCase();
      if (!['done', 'skipped'].includes(itemStatus)) {
        return `${item.title}：${item.description}`;
      }
    }
    return '本轮流程已完成，可继续查看知识图谱结果。';
  });

  function closeResearchSocket() {
    if (researchSocket) {
      researchSocket.close();
      researchSocket = null;
    }
  }

  function stopResearchPolling() {
    if (researchPollTimer) {
      window.clearInterval(researchPollTimer);
      researchPollTimer = null;
    }
  }

  function markInsightStreamHeartbeat() {
    lastInsightStreamAt.value = Date.now();
  }

  function stopInsightStreamWatchdog() {
    if (insightStreamWatchdogTimer) {
      window.clearInterval(insightStreamWatchdogTimer);
      insightStreamWatchdogTimer = null;
    }
    insightStreamReconcileInFlight = false;
  }

  function startInsightStreamWatchdog() {
    if (insightStreamWatchdogTimer || typeof window === 'undefined') return;
    insightStreamWatchdogTimer = window.setInterval(() => {
      if (!unifiedRuntimeActive.value) return;
      const insightStep = steps.value.find((item) => item.key === 'insight');
      const insightStepStatus = String(insightStep?.status || '').trim().toLowerCase();
      const shouldWatch = Boolean(
        insightReportStreaming.value
        || (insightStepStatus === 'running' && !insightReportReady.value)
      );
      if (!shouldWatch) return;
      const lastAt = Number(lastInsightStreamAt.value || 0);
      if (!Number.isFinite(lastAt) || lastAt <= 0) {
        markInsightStreamHeartbeat();
        return;
      }
      if (Date.now() - lastAt < INSIGHT_STREAM_STALL_MS) return;
      if (insightStreamReconcileInFlight) return;
      insightStreamReconcileInFlight = true;
      void refreshRuntimeSnapshot().finally(() => {
        insightStreamReconcileInFlight = false;
      });
    }, INSIGHT_STREAM_WATCHDOG_INTERVAL_MS);
  }

  function reconcileInsightProgressFromSnapshot(snapshot = {}) {
    const status = String(snapshot?.status || '').trim().toLowerCase();
    const waiting = String(snapshot?.waiting_checkpoint || '').trim().toLowerCase();
    const currentNode = String(snapshot?.current_node || '').trim().toLowerCase();
    const insightPayload = snapshot?.insight && typeof snapshot.insight === 'object' ? snapshot.insight : {};
    const serverMarkdown = String(insightPayload?.markdown || snapshot?.report || '').trim();
    const insightStep = steps.value.find((item) => item.key === 'insight');
    const insightStepStatus = String(insightStep?.status || '').trim().toLowerCase();

    if (serverMarkdown) {
      insightReportMarkdown.value = serverMarkdown;
      insightStreamAccumulatedChars.value = Math.max(
        insightStreamAccumulatedChars.value,
        serverMarkdown.length
      );
      insightReportReady.value = true;
      insightReportStreaming.value = false;
      markInsightStreamHeartbeat();
      if (status !== 'completed') {
        setStepStatusByKey('insight', 'running', '探索报告已生成，正在保存与收敛。');
      }
      return true;
    }

    if (
      status === 'running'
      && waiting !== 'checkpoint_2'
      && (insightStepStatus === 'action_required' || currentNode === 'insight' || currentNode === 'checkpoint_2')
    ) {
      markEarlierStepsDone('insight');
      setStepAction('insight', null);
      insightConfigSubmitting.value = false;
      setStepStatusByKey('insight', 'running', '正在执行 Insight Agent。');
      markInsightStreamHeartbeat();
      return true;
    }

    if (status === 'completed') {
      insightReportStreaming.value = false;
      insightReportReady.value = Boolean(String(insightReportMarkdown.value || '').trim());
      markInsightStreamHeartbeat();
      return true;
    }

    if (status === 'failed' || status === 'stopped') {
      insightReportStreaming.value = false;
      markInsightStreamHeartbeat();
      return true;
    }

    return false;
  }

  function resetNegotiationState() {
    negotiationByStep.value = createNegotiationStateByStep();
  }

  function updateStepSignal() {
    const step = activeStep.value || steps.value[0] || { index: 1, title: '论文检索' };
    notifyStepChange({
      index: Number(step.index || 1),
      total: steps.value.length,
      title: String(step.title || '论文检索')
    });
  }

  function buildCompletedStepSummary(step) {
    const key = String(step?.key || '').trim();
    const defaultTitleByKey = {
      retrieve: 'Retriever Agent',
      checkpoint: 'Coordinator Agent',
      graph: 'Graph Builder Agent',
      insight: 'Insight Agent'
    };
    const defaultDetailByKey = {
      retrieve: '论文检索已完成。',
      checkpoint: '需求确认已完成。',
      graph: '知识图谱生成已完成。',
      insight: '探索与洞察已完成。'
    };
    return {
      title: defaultTitleByKey[key] || 'Coordinator Agent',
      detail: String(step?.message || '').trim() || defaultDetailByKey[key] || `${step?.title || '步骤'}已完成。`,
      status: 'done',
      statusText: toStatusText('done'),
      metaText: ''
    };
  }

  function finalizeStepLogs(step) {
    if (!step || !Array.isArray(step.logs) || !step.logs.length) return;
    step.logs = step.logs.map((log) => {
      const normalized = String(log?.status || '').trim().toLowerCase();
      if (normalized === 'doing' || normalized === 'pending' || normalized === 'running') {
        return {
          ...log,
          status: 'done',
          statusText: toStatusText('done')
        };
      }
      return log;
    });
  }

  function ensureStepHasVisibleDetails(step) {
    if (!step || !Array.isArray(step.logs) || step.logs.length) return;
    step.logs = [buildCompletedStepSummary(step)];
  }

  function settleStepTransientLogs(step) {
    if (!step || !Array.isArray(step.logs) || !step.logs.length) return;
    step.logs = step.logs.map((log) => {
      const normalized = String(log?.status || '').trim().toLowerCase();
      if (normalized === 'doing' || normalized === 'pending' || normalized === 'running') {
        return {
          ...log,
          status: 'done',
          statusText: toStatusText('done')
        };
      }
      return log;
    });
  }

  function setStepStatus(index, status, message = '') {
    const target = steps.value.find((item) => item.index === index);
    if (!target) return;
    target.status = status;
    target.message = message;
    const normalizedStatus = String(status || '').trim().toLowerCase();
    if (normalizedStatus === 'done' || normalizedStatus === 'skipped') {
      finalizeStepLogs(target);
      ensureStepHasVisibleDetails(target);
    }
    updateStepSignal();
  }

  function setStepStatusByKey(stepKey, status, message = '') {
    const target = steps.value.find((item) => item.key === String(stepKey || '').trim());
    if (!target) return;
    setStepStatus(target.index, status, message);
  }

  function setStepLogs(stepKey, logs) {
    const target = steps.value.find((item) => item.key === String(stepKey || '').trim());
    if (!target) return;
    target.logs = Array.isArray(logs) ? logs : [];
  }

  function setStepAction(stepKey, action) {
    const target = steps.value.find((item) => item.key === String(stepKey || '').trim());
    if (!target || !Object.prototype.hasOwnProperty.call(target, 'action')) return;
    target.action = action || null;
  }

  function appendStepLog(stepKey, logItem) {
    const target = steps.value.find((item) => item.key === String(stepKey || '').trim());
    if (!target) return;
    const stepStatus = String(target.status || '').trim().toLowerCase();
    const requestedStatus = String(logItem?.status || 'pending').trim() || 'pending';
    const normalizedRequestedStatus = String(requestedStatus || '').trim().toLowerCase();
    const safeStatus = (
      ['done', 'skipped'].includes(stepStatus)
      && ['doing', 'pending', 'running'].includes(normalizedRequestedStatus)
    )
      ? 'done'
      : requestedStatus;

    const nextLog = {
      title: String(logItem?.title || '').trim() || '执行记录',
      detail: String(logItem?.detail || '').trim() || '工作流运行中。',
      status: safeStatus,
      statusText: toStatusText(safeStatus),
      metaText: String(logItem?.metaText || '').trim()
    };

    const previous = Array.isArray(target.logs) ? target.logs[target.logs.length - 1] : null;
    if (
      previous
      && previous.title === nextLog.title
      && previous.detail === nextLog.detail
      && previous.status === nextLog.status
    ) {
      return;
    }

    settleStepTransientLogs(target);
    target.logs = [...(Array.isArray(target.logs) ? target.logs : []), nextLog];
  }

  function appendFailureLog(stepKey, detail) {
    const target = steps.value.find((item) => item.key === String(stepKey || '').trim());
    if (!target) return;
    const nextLogs = [
      ...(target.logs || []),
      {
        title: '执行异常',
        detail: String(detail || '').trim() || '步骤执行失败。',
        status: 'fallback',
        statusText: toStatusText('error'),
        metaText: ''
      }
    ];
    setStepLogs(stepKey, nextLogs);
  }

  function appendNodeLog(node, detail, status = 'doing') {
    const stepKey = resolveStepKeyByNode(node);
    const title = resolveNodeLabel(node);
    const target = steps.value.find((item) => item.key === stepKey);
    if (!target) return;

    settleStepTransientLogs(target);
    const logs = Array.isArray(target.logs) ? [...target.logs] : [];
    const logIndex = logs.length;
    logs.push({
      title,
      detail: String(detail || '').trim() || '工作流运行中。',
      status,
      statusText: toStatusText(status),
      metaText: ''
    });
    target.logs = logs;
    runtimeNodeLogCursor.set(`${stepKey}::${String(node || '').trim()}`, logIndex);
  }

  function updateLatestNodeLog(stepKey, node, patch = {}) {
    const cursorKey = `${String(stepKey || '').trim()}::${String(node || '').trim()}`;
    const logIndex = runtimeNodeLogCursor.get(cursorKey);
    if (!Number.isInteger(logIndex)) return;
    const target = steps.value.find((item) => item.key === String(stepKey || '').trim());
    if (!target || !Array.isArray(target.logs) || !target.logs[logIndex]) return;
    if (logIndex !== target.logs.length - 1) return;

    const requestedStatus = String(patch?.status || target.logs[logIndex].status || 'pending');
    const stepStatus = String(target.status || '').trim().toLowerCase();
    const normalizedRequestedStatus = String(requestedStatus || '').trim().toLowerCase();
    const nextStatus = (
      ['done', 'skipped'].includes(stepStatus)
      && ['doing', 'pending', 'running'].includes(normalizedRequestedStatus)
    )
      ? 'done'
      : requestedStatus;

    target.logs[logIndex] = {
      ...target.logs[logIndex],
      ...patch,
      status: nextStatus,
      statusText: toStatusText(nextStatus)
    };
  }

  function markEarlierStepsDone(stepKey) {
    const targetIndex = STEP_FLOW_ORDER.indexOf(String(stepKey || '').trim());
    if (targetIndex <= 0) return;
    for (let index = 0; index < targetIndex; index += 1) {
      const key = STEP_FLOW_ORDER[index];
      const step = steps.value.find((item) => item.key === key);
      if (!step) continue;
      const status = String(step.status || '').trim().toLowerCase();
      if (!['done', 'skipped'].includes(status)) {
        step.status = 'done';
        if (!String(step.message || '').trim()) {
          step.message = `${step.title}已完成。`;
        }
      }
      finalizeStepLogs(step);
      ensureStepHasVisibleDetails(step);
    }
  }

  function resolveNegotiationTimestamp(event = {}) {
    const ts = String(event?.ts || '').trim();
    return ts || new Date().toISOString();
  }

  function normalizeNegotiationRound(rawRound) {
    const parsed = Number(rawRound);
    if (!Number.isFinite(parsed) || parsed <= 0) return 1;
    return Math.max(1, Math.round(parsed));
  }

  function ensureNegotiationStepState(stepKey) {
    const safeKey = STEP_FLOW_ORDER.includes(stepKey) ? stepKey : 'retrieve';
    const existing = negotiationByStep.value[safeKey];
    if (existing && typeof existing === 'object' && Array.isArray(existing.rounds)) {
      return existing;
    }
    negotiationByStep.value[safeKey] = createNegotiationStepState();
    return negotiationByStep.value[safeKey];
  }

  function ensureNegotiationRoundState({
    stepKey,
    event = {},
    defaultStatus = 'bidding'
  }) {
    const safeTaskId = String(event?.task_id || '').trim();
    const safeTaskKind = String(event?.task_kind || '').trim().toLowerCase();
    const roundIndex = normalizeNegotiationRound(event?.round);
    const stepState = ensureNegotiationStepState(stepKey);
    const updatedAt = resolveNegotiationTimestamp(event);

    let roundState = stepState.rounds.find((item) => {
      if (Number(item?.round) !== roundIndex) return false;
      if (!safeTaskId) return true;
      if (!String(item?.taskId || '').trim()) return true;
      return String(item.taskId || '').trim() === safeTaskId;
    });

    if (!roundState) {
      roundState = createNegotiationRoundState({
        round: roundIndex,
        taskId: safeTaskId,
        taskKind: safeTaskKind,
        status: defaultStatus,
        updatedAt
      });
      stepState.rounds.push(roundState);
    } else {
      if (safeTaskId && !String(roundState.taskId || '').trim()) {
        roundState.taskId = safeTaskId;
      }
      if (safeTaskKind) {
        roundState.taskKind = safeTaskKind;
      }
      if (!String(roundState.status || '').trim()) {
        roundState.status = defaultStatus;
      }
      roundState.updatedAt = updatedAt;
    }

    stepState.activeRound = roundIndex;
    if (safeTaskKind) {
      stepState.activeTaskKind = safeTaskKind;
    }

    return {
      stepState,
      roundState
    };
  }

  function resolveAgentRuntimeLabel(rawAgentId, rawProfile) {
    const agentId = String(rawAgentId || '').trim().toLowerCase();
    const profile = String(rawProfile || '').trim().toLowerCase();
    let base = 'Coordinator Agent';
    if (agentId.includes('planner')) base = 'Planner Agent';
    else if (agentId.includes('router')) base = 'Router Agent';
    else if (agentId.includes('search')) base = 'Retriever Agent';
    else if (agentId.includes('graph')) base = 'Graph Builder Agent';
    else if (agentId.includes('checkpoint_1')) base = 'Human Checkpoint';
    else if (agentId.includes('checkpoint_2')) base = 'Insight Checkpoint';
    else if (agentId.includes('insight')) base = 'Insight Agent';
    const profileLabel = NEGOTIATION_PROFILE_LABEL[profile] || NEGOTIATION_PROFILE_LABEL[agentId.split('_').at(-1)] || '';
    if (!profileLabel) return base;
    return `${base} · ${profileLabel}`;
  }

  function buildNegotiationBid(event = {}) {
    const agentId = String(event?.agent_id || '').trim();
    const profile = String(event?.profile || '').trim().toLowerCase();
    return {
      agentId,
      profile,
      label: resolveAgentRuntimeLabel(agentId, profile),
      confidence: toFiniteNegotiationNumber(event?.confidence),
      estimatedLatencyMs: toFiniteNegotiationNumber(event?.estimated_latency_ms),
      estimatedCost: toFiniteNegotiationNumber(event?.estimated_cost),
      rationale: String(event?.rationale || '').trim(),
      status: 'bid'
    };
  }

  function mergeWinnerBidMetrics(existingBid = {}, incomingBid = {}) {
    const merged = {
      ...existingBid,
      ...incomingBid
    };
    if (!hasNegotiationMetricValue(incomingBid?.confidence) && hasNegotiationMetricValue(existingBid?.confidence)) {
      merged.confidence = existingBid.confidence;
    }
    if (!hasNegotiationMetricValue(incomingBid?.estimatedLatencyMs) && hasNegotiationMetricValue(existingBid?.estimatedLatencyMs)) {
      merged.estimatedLatencyMs = existingBid.estimatedLatencyMs;
    }
    if (!hasNegotiationMetricValue(incomingBid?.estimatedCost) && hasNegotiationMetricValue(existingBid?.estimatedCost)) {
      merged.estimatedCost = existingBid.estimatedCost;
    }
    return merged;
  }

  function upsertNegotiationBid(roundState, nextBid) {
    if (!roundState || !nextBid) return;
    const safeAgentId = String(nextBid.agentId || '').trim();
    const safeProfile = String(nextBid.profile || '').trim().toLowerCase();
    if (!safeAgentId) return;

    const index = roundState.bids.findIndex((item) => (
      String(item?.agentId || '').trim() === safeAgentId
      && String(item?.profile || '').trim().toLowerCase() === safeProfile
    ));

    if (index >= 0) {
      roundState.bids[index] = {
        ...roundState.bids[index],
        ...nextBid
      };
      return;
    }

    roundState.bids.push(nextBid);
  }

  function assignNegotiationWinner(roundState, winnerBid) {
    if (!roundState || !winnerBid) return;
    const safeAgentId = String(winnerBid.agentId || '').trim();
    const safeProfile = String(winnerBid.profile || '').trim().toLowerCase();
    if (!safeAgentId) return;

    let winnerRef = null;
    for (const bid of roundState.bids) {
      const bidAgentId = String(bid?.agentId || '').trim();
      const bidProfile = String(bid?.profile || '').trim().toLowerCase();
      const matched = bidAgentId === safeAgentId && (!safeProfile || bidProfile === safeProfile);
      if (matched) {
        bid.status = 'winner';
        winnerRef = bid;
      } else if (String(bid?.status || '').trim().toLowerCase() === 'winner') {
        bid.status = 'bid';
      }
    }

    if (!winnerRef) {
      winnerRef = {
        ...winnerBid,
        status: 'winner'
      };
      roundState.bids.push(winnerRef);
    } else {
      Object.assign(
        winnerRef,
        mergeWinnerBidMetrics(winnerRef, winnerBid),
        { status: 'winner' }
      );
    }

    roundState.winner = {
      agentId: winnerRef.agentId,
      profile: winnerRef.profile,
      label: winnerRef.label,
      confidence: winnerRef.confidence,
      estimatedLatencyMs: winnerRef.estimatedLatencyMs,
      estimatedCost: winnerRef.estimatedCost,
      rationale: winnerRef.rationale,
      status: winnerRef.status
    };
  }

  function normalizeNegotiationStateForCompletedWorkflow() {
    for (const stepKey of STEP_FLOW_ORDER) {
      const step = steps.value.find((item) => item.key === stepKey);
      if (!step) continue;
      const stepStatus = String(step.status || '').trim().toLowerCase();
      if (!['done', 'skipped'].includes(stepStatus)) continue;

      const stepState = negotiationByStep.value?.[stepKey];
      if (!stepState || !Array.isArray(stepState.rounds) || !stepState.rounds.length) continue;
      if (!Number.isFinite(Number(stepState.activeRound)) || Number(stepState.activeRound) <= 0) {
        const lastRound = stepState.rounds[stepState.rounds.length - 1];
        stepState.activeRound = Number(lastRound?.round || 1);
      }

      for (const round of stepState.rounds) {
        const bids = Array.isArray(round?.bids) ? round.bids : [];
        const winnerFromBids = bids.find((item) => String(item?.status || '').trim().toLowerCase() === 'winner') || null;
        if (!round.winner && winnerFromBids) {
          round.winner = {
            ...winnerFromBids,
            status: 'winner'
          };
        }
        if (!round.winner && bids.length) {
          const fallbackWinner = bids[0];
          fallbackWinner.status = 'winner';
          round.winner = {
            ...fallbackWinner,
            status: 'winner'
          };
        }

        const normalizedRoundStatus = String(round?.status || '').trim().toLowerCase();
        if (normalizedRoundStatus === 'bidding' || !normalizedRoundStatus) {
          round.status = round?.veto ? 'vetoed' : (round?.rebid ? 'rebid' : 'awarded');
        }
      }
    }
  }

  function persistActiveRuntimeSessionSnapshot(snapshot = {}) {
    const sessionId = String(snapshot?.session_id || researchSessionId.value || '').trim();
    if (!sessionId) return;
    const snapshotProgress = Number(snapshot?.progress);
    const doneCount = steps.value.filter((item) => item.status === 'done').length;
    const fallbackProgress = Math.max(
      0,
      Math.min(100, Math.round((doneCount / Math.max(1, steps.value.length)) * 100))
    );

    persistActiveResearchSessionRecord({
      session_id: sessionId,
      status: String(snapshot?.status || 'running').trim().toLowerCase(),
      progress: Number.isFinite(snapshotProgress) ? snapshotProgress : fallbackProgress,
      current_node: String(snapshot?.current_node || '').trim(),
      waiting_checkpoint: String(snapshot?.waiting_checkpoint || waitingResearchCheckpoint.value || '').trim(),
      input_type: String(snapshot?.input_type || runtimeSeed.value.input_type || 'domain').trim().toLowerCase(),
      input_value: String(snapshot?.input_value || runtimeSeed.value.input_value || '').trim(),
      paper_range_years: snapshot?.paper_range_years ?? runtimeSeed.value.paper_range_years,
      quick_mode: Boolean(
        snapshot?.quick_mode !== undefined
          ? snapshot.quick_mode
          : runtimeSeed.value.quick_mode
      ),
      updated_at: new Date().toISOString()
    });
  }

  function finalizeAllRuntimeTraceStatuses() {
    for (const step of steps.value) {
      if (!Array.isArray(step.logs) || !step.logs.length) continue;
      step.logs = step.logs.map((log) => {
        const status = String(log?.status || '').trim().toLowerCase();
        if (status === 'doing' || status === 'pending') {
          return {
            ...log,
            status: 'done',
            statusText: toStatusText('done')
          };
        }
        return log;
      });
    }
  }

  function ensureCompletedWorkflowStepLogs() {
    for (const step of steps.value) {
      const status = String(step?.status || '').trim().toLowerCase();
      if (!['done', 'completed', 'skipped'].includes(status)) continue;
      finalizeStepLogs(step);
      ensureStepHasVisibleDetails(step);
    }
  }

  function buildGraphSignature(rawGraph = {}) {
    const graphId = String(rawGraph?.graph_id || '').trim();
    const nodes = Array.isArray(rawGraph?.nodes) ? rawGraph.nodes : [];
    const edges = Array.isArray(rawGraph?.edges) ? rawGraph.edges : [];
    const nodePreview = nodes
      .map((item) => String(item?.id || item?.label || '').trim())
      .filter(Boolean)
      .sort()
      .slice(0, 24)
      .join('|');
    const edgePreview = edges
      .map((item) => `${String(item?.source || '').trim()}>${String(item?.target || '').trim()}`)
      .filter((item) => item !== '>')
      .sort()
      .slice(0, 24)
      .join('|');
    return `${graphId || 'graph'}#n${nodes.length}#e${edges.length}#${nodePreview}#${edgePreview}`;
  }

  function buildPreviewGraphSignature(query, papers) {
    const safeQuery = String(query || '').trim().toLowerCase();
    const sourcePapers = Array.isArray(papers) ? papers : [];
    const topIds = sourcePapers
      .slice(0, 12)
      .map((item) => String(item?.paper_id || item?.title || '').trim())
      .filter(Boolean)
      .sort()
      .join('|');
    return `preview#${safeQuery}#${sourcePapers.length}#${topIds}`;
  }

  function commitGraphData(nextGraph, signature) {
    if (!nextGraph || typeof nextGraph !== 'object') return false;
    const nextSignature = String(signature || '').trim();
    if (nextSignature && nextSignature === graphSnapshotSignature.value) return false;
    graphData.value = nextGraph;
    graphSnapshotSignature.value = nextSignature;
    return true;
  }

  function hydrateRuntimeArtifacts(snapshot = {}) {
    const fallbackReport = String(snapshot?.report || '').trim();
    if (snapshot?.insight && typeof snapshot.insight === 'object') {
      const insightPayload = snapshot.insight;
      const markdown = String(insightPayload?.markdown || fallbackReport).trim();
      const language = String(insightPayload?.language || '').trim().toLowerCase();
      syncInsightInlineConfig({
        agent_count: insightPayload?.agent_count,
        exploration_depth: insightPayload?.exploration_depth
      });
      if (markdown) {
        insightReportMarkdown.value = markdown;
        insightStreamAccumulatedChars.value = markdown.length;
      }
      insightReportLanguage.value = language === 'en' ? 'en' : 'zh';
      insightReportReady.value = String(insightPayload?.status || '').trim().toLowerCase() === 'completed' || Boolean(markdown);
      if (insightReportReady.value) {
        insightReportStreaming.value = false;
      }
    } else if (fallbackReport) {
      insightReportMarkdown.value = fallbackReport;
      insightStreamAccumulatedChars.value = Math.max(
        insightStreamAccumulatedChars.value,
        fallbackReport.length
      );
      insightReportReady.value = Boolean(fallbackReport);
      if (String(snapshot?.status || '').trim().toLowerCase() === 'completed') {
        insightReportStreaming.value = false;
      }
    }

    if (snapshot?.graph && typeof snapshot.graph === 'object') {
      commitGraphData(snapshot.graph, buildGraphSignature(snapshot.graph));
      return;
    }

    if (Array.isArray(snapshot?.papers) && snapshot.papers.length) {
      const previewQuery = snapshot?.research_goal || snapshot?.input_value || runtimeSeed.value.input_value;
      const previewSignature = buildPreviewGraphSignature(previewQuery, snapshot.papers);
      const previewGraph = buildRetrievalPreviewGraph(previewQuery, snapshot.papers);
      commitGraphData(previewGraph, previewSignature);
    }
  }

  function persistCompletedWorkflowSnapshotFromState() {
    const seedPayload = runtimeSeed.value?.input_value
      ? runtimeSeed.value
      : normalizeRuntimeSeed(seedRef.value || {});

    const stepsPayload = steps.value.map((step) => ({
      index: Number(step?.index || 0),
      key: String(step?.key || '').trim(),
      status: String(step?.status || '').trim().toLowerCase(),
      message: String(step?.message || '').trim(),
      logs: safeJsonClone(Array.isArray(step?.logs) ? step.logs : [], []),
      action: null
    }));

    writeCompletedWorkflowSnapshot({
      status: 'completed',
      session_id: String(researchSessionId.value || '').trim(),
      seed_fingerprint: buildWorkflowSeedFingerprint(seedPayload),
      saved_at: new Date().toISOString(),
      steps: stepsPayload,
      negotiation_by_step: safeJsonClone(negotiationByStep.value, createNegotiationStateByStep()),
      graph: graphData.value && typeof graphData.value === 'object'
        ? safeJsonClone(graphData.value, null)
        : null,
      insight: {
        markdown: insightReportMarkdown.value,
        language: insightReportLanguage.value,
        ready: Boolean(insightReportReady.value)
      }
    });
  }

  function restoreCompletedWorkflowSnapshotFromStorage() {
    const snapshot = readCompletedWorkflowSnapshot();
    if (!snapshot || typeof snapshot !== 'object') return false;
    if (String(snapshot?.status || '').trim().toLowerCase() !== 'completed') return false;

    const currentSeed = normalizeRuntimeSeed(seedRef.value || {});
    const expectedFingerprint = buildWorkflowSeedFingerprint(currentSeed);
    if (String(snapshot?.seed_fingerprint || '').trim() !== expectedFingerprint) return false;

    const stepRecords = Array.isArray(snapshot?.steps) ? snapshot.steps : [];
    const stepRecordByKey = new Map();
    for (const item of stepRecords) {
      const key = String(item?.key || '').trim();
      if (!key) continue;
      stepRecordByKey.set(key, item);
    }

    for (const step of steps.value) {
      const record = stepRecordByKey.get(String(step?.key || '').trim()) || {};
      step.status = 'done';
      step.message = String(record?.message || step?.message || `${step.title}已完成。`).trim();
      step.logs = safeJsonClone(Array.isArray(record?.logs) ? record.logs : (Array.isArray(step.logs) ? step.logs : []), []);
      if (!Array.isArray(step.logs)) step.logs = [];
      if (Object.prototype.hasOwnProperty.call(step, 'action')) step.action = null;
      finalizeStepLogs(step);
      ensureStepHasVisibleDetails(step);
    }

    const restoredNegotiation = snapshot?.negotiation_by_step;
    negotiationByStep.value = safeJsonClone(
      restoredNegotiation && typeof restoredNegotiation === 'object'
        ? restoredNegotiation
        : createNegotiationStateByStep(),
      createNegotiationStateByStep()
    );

    normalizeNegotiationStateForCompletedWorkflow();
    finalizeAllRuntimeTraceStatuses();
    ensureCompletedWorkflowStepLogs();

    const restoredGraph = snapshot?.graph;
    if (restoredGraph && typeof restoredGraph === 'object') {
      commitGraphData(restoredGraph, buildGraphSignature(restoredGraph));
    }

    const restoredInsight = snapshot?.insight;
    if (restoredInsight && typeof restoredInsight === 'object') {
      insightReportMarkdown.value = String(restoredInsight?.markdown || '').trim();
      insightReportLanguage.value = String(restoredInsight?.language || '').trim().toLowerCase() === 'en' ? 'en' : 'zh';
      insightReportReady.value = Boolean(restoredInsight?.ready) || Boolean(insightReportMarkdown.value);
      insightReportStreaming.value = false;
      insightStreamAccumulatedChars.value = insightReportMarkdown.value.length;
    }

    waitingResearchCheckpoint.value = '';
    runtimeAutoResumingCheckpoint.value = '';
    graphLoading.value = false;
    unifiedRuntimeActive.value = false;
    researchSessionId.value = String(snapshot?.session_id || '').trim();
    if (researchSessionId.value) {
      runtimeSeed.value = {
        ...runtimeSeed.value,
        runtime_session_id: researchSessionId.value
      };
    }
    errorMessage.value = '';
    clearActiveResearchSessionRecord();
    stopResearchPolling();
    closeResearchSocket();
    updateStepSignal();
    return true;
  }

  function resolveFailureStepKey(message, currentNode = '', waitingCheckpoint = '') {
    const errorText = String(message || '').trim().toLowerCase();
    if (errorText) {
      const matchedTask = errorText.match(
        /(?:negotiation_budget_exhausted|no_agent_bid_for_task|critic_rejected|agent_execution_failed):([a-z0-9_]+)/i
      );
      if (matchedTask && matchedTask[1]) {
        return resolveStepKeyByTaskKind(matchedTask[1]);
      }
    }

    const checkpoint = String(waitingCheckpoint || '').trim().toLowerCase();
    if (checkpoint === 'checkpoint_1') return 'checkpoint';
    if (checkpoint === 'checkpoint_2') return 'insight';
    return resolveStepKeyByNode(currentNode || 'search');
  }

  function resetUnifiedRuntimeState() {
    stopResearchPolling();
    stopInsightStreamWatchdog();
    closeResearchSocket();
    researchSessionId.value = '';
    unifiedRuntimeActive.value = false;
    waitingResearchCheckpoint.value = '';
    runtimeAutoResumingCheckpoint.value = '';
    graphSnapshotSignature.value = '';
    lastInsightStreamAt.value = 0;
    runtimeLastEventTsMs = 0;
    runtimeNodeLogCursor.clear();
    graphStreamCursor.clear();
    resetNegotiationState();
  }

  function resetSteps() {
    runtimeNodeLogCursor.clear();
    graphStreamCursor.clear();
    resetNegotiationState();
    syncInsightInlineConfig({
      agent_count: INSIGHT_AGENT_COUNT_DEFAULT,
      exploration_depth: INSIGHT_DEPTH_DEFAULT
    });
    insightConfigSubmitting.value = false;
    insightReportMarkdown.value = '';
    insightReportLanguage.value = 'zh';
    insightReportReady.value = false;
    insightReportStreaming.value = false;
    insightStreamAccumulatedChars.value = 0;
    lastInsightStreamAt.value = 0;
    insightMarkdownDownloadLoading.value = false;
    insightPdfDownloadLoading.value = false;
    for (const step of steps.value) {
      step.status = 'pending';
      step.message = '';
      step.logs = [];
      if (Object.prototype.hasOwnProperty.call(step, 'action')) {
        step.action = null;
      }
    }
    updateStepSignal();
  }

  async function playRetrievalTrace(rawSteps) {
    const inputType = String(seedRef.value?.input_type || 'domain').trim().toLowerCase();
    const items = Array.isArray(rawSteps) ? rawSteps.map((item) => normalizeTraceStep(item, inputType)) : [];
    if (!items.length) return;
    const evolving = [];
    for (const item of items) {
      evolving.push({
        ...item,
        status: 'doing',
        statusText: toStatusText('doing')
      });
      setStepLogs('retrieve', [...evolving]);
      await sleep(220);
      evolving[evolving.length - 1] = item;
      setStepLogs('retrieve', [...evolving]);
    }
  }

  async function playBuildTrace(rawSteps) {
    const items = Array.isArray(rawSteps) ? rawSteps.map(normalizeBuildTraceStep) : [];
    if (!items.length) return;
    const evolving = [];
    for (const item of items) {
      evolving.push({
        ...item,
        status: 'doing',
        statusText: toStatusText('doing')
      });
      setStepLogs('graph', [...evolving]);
      await sleep(240);
      evolving[evolving.length - 1] = item;
      setStepLogs('graph', [...evolving]);
    }
  }

  function shouldAutoConfirmCheckpoint(checkpointNode) {
    return String(checkpointNode || '').trim().toLowerCase() === 'checkpoint_1';
  }

  function resolveCheckpointForStep(stepKey) {
    const safeStepKey = String(stepKey || '').trim().toLowerCase();
    if (safeStepKey === 'checkpoint') return 'checkpoint_1';
    if (safeStepKey === 'insight') return 'checkpoint_2';
    return '';
  }

  function resolveAutoCheckpointDoneMessage(checkpointNode) {
    const normalized = String(checkpointNode || '').trim().toLowerCase();
    if (normalized === 'checkpoint_1') {
      return '检索阶段已确认，系统自动继续生成知识图谱。';
    }
    if (normalized === 'checkpoint_2') {
      return '探索参数已确认，系统正在启动探索任务。';
    }
    return '已自动确认，正在继续执行。';
  }

  function normalizeInsightConfigValue(rawValue, { min, max, fallback }) {
    const parsed = Number.parseInt(String(rawValue || '').trim(), 10);
    if (!Number.isFinite(parsed)) return String(fallback);
    return String(Math.max(min, Math.min(max, parsed)));
  }

  function syncInsightInlineConfig(payload = {}) {
    const nextAgent = normalizeInsightConfigValue(payload?.agent_count, {
      min: INSIGHT_AGENT_COUNT_MIN,
      max: INSIGHT_AGENT_COUNT_MAX,
      fallback: INSIGHT_AGENT_COUNT_DEFAULT
    });
    const nextDepth = normalizeInsightConfigValue(payload?.exploration_depth, {
      min: INSIGHT_DEPTH_MIN,
      max: INSIGHT_DEPTH_MAX,
      fallback: INSIGHT_DEPTH_DEFAULT
    });
    insightAgentCountDraft.value = nextAgent;
    insightDepthDraft.value = nextDepth;
  }

  function updateInsightInlineConfig(field, value) {
    const safeField = String(field || '').trim().toLowerCase();
    if (safeField === 'agent_count') {
      insightAgentCountDraft.value = normalizeInsightConfigValue(value, {
        min: INSIGHT_AGENT_COUNT_MIN,
        max: INSIGHT_AGENT_COUNT_MAX,
        fallback: INSIGHT_AGENT_COUNT_DEFAULT
      });
      return;
    }
    if (safeField === 'exploration_depth') {
      insightDepthDraft.value = normalizeInsightConfigValue(value, {
        min: INSIGHT_DEPTH_MIN,
        max: INSIGHT_DEPTH_MAX,
        fallback: INSIGHT_DEPTH_DEFAULT
      });
    }
  }

  async function continueAfterUnifiedCheckpoint(stepKey, options = {}) {
    const auto = Boolean(options?.auto);
    const feedbackPayload = options?.feedbackPayload && typeof options.feedbackPayload === 'object'
      ? options.feedbackPayload
      : null;
    const safeStepKey = String(stepKey || '').trim();
    const checkpoint = String(waitingResearchCheckpoint.value || '').trim().toLowerCase();
    if (!safeStepKey || !checkpoint) return;
    const expectedCheckpoint = resolveCheckpointForStep(safeStepKey);
    if (!expectedCheckpoint || checkpoint !== expectedCheckpoint) return;

    const sessionId = String(researchSessionId.value || '').trim();
    if (!sessionId) return;

    const scheduleCheckpointAutoRetry = () => {
      const target = steps.value.find((item) => item.key === 'checkpoint');
      if (target) {
        setStepStatus(target.index, 'running', '自动继续失败，正在重试...');
      }
      runtimeAutoResumingCheckpoint.value = '';
      window.setTimeout(() => {
        if (!unifiedRuntimeActive.value) return;
        const waiting = String(waitingResearchCheckpoint.value || '').trim().toLowerCase();
        if (waiting !== checkpoint) return;
        runtimeAutoResumingCheckpoint.value = checkpoint;
        void continueAfterUnifiedCheckpoint('checkpoint', { auto: true });
      }, 1200);
    };

    const feedback = feedbackPayload || '';

    try {
      const result = await resumeResearchSession(
        sessionId,
        feedback,
        { accessToken: accessTokenRef.value || '' }
      );
      if (!result?.resumed) {
        if (auto && safeStepKey === 'checkpoint') {
          scheduleCheckpointAutoRetry();
        }
        return;
      }

      waitingResearchCheckpoint.value = '';
      runtimeAutoResumingCheckpoint.value = '';

      const target = steps.value.find((item) => item.key === safeStepKey);
      if (target) {
        setStepStatus(
          target.index,
          'running',
          auto
            ? '已自动确认，正在继续执行。'
            : (safeStepKey === 'insight' ? '参数已确认，正在启动探索与洞察。' : '已确认，正在继续执行。')
        );
      }
      if (safeStepKey === 'insight') {
        setStepAction('insight', null);
        insightReportStreaming.value = true;
      }
    } catch {
      runtimeAutoResumingCheckpoint.value = '';
      if (auto && safeStepKey === 'checkpoint') {
        scheduleCheckpointAutoRetry();
      }
    }
  }

  function handleRuntimeNodeStart(event = {}) {
    const node = String(event?.node || '').trim().toLowerCase();
    if (!node) return;
    const stepKey = resolveStepKeyByNode(node);
    const step = steps.value.find((item) => item.key === stepKey);
    if (!step) return;

    markEarlierStepsDone(stepKey);
    const runningMessage = `正在执行 ${resolveNodeLabel(node)}。`;
    setStepStatus(step.index, 'running', runningMessage);
    appendNodeLog(node, runningMessage, 'doing');

    if (node === 'graph_build') {
      void refreshRuntimeSnapshot().catch(() => {
        // keep graph stage resilient when snapshot fetch is transiently unavailable
      });
    }
    if (node === 'insight') {
      insightReportStreaming.value = false;
      insightReportReady.value = false;
      insightStreamAccumulatedChars.value = Math.max(0, String(insightReportMarkdown.value || '').length);
      setStepStatusByKey('insight', 'running', '正在汇总并生成报告...');
      markInsightStreamHeartbeat();
    }

    setStepAction('checkpoint', null);
    setStepAction('insight', null);
  }

  function handleRuntimeThinking(event = {}) {
    const node = String(event?.node || '').trim().toLowerCase();
    if (!node) return;
    const content = String(event?.content || '').trim();
    if (!content) return;

    const stepKey = resolveStepKeyByNode(node);
    if (!steps.value.find((item) => item.key === stepKey)) return;

    const cursorKey = `${stepKey}::${node}`;
    if (runtimeNodeLogCursor.has(cursorKey)) {
      updateLatestNodeLog(stepKey, node, { detail: content, status: 'doing' });
      return;
    }
    appendNodeLog(node, content, 'doing');
  }

  async function handleRuntimeNodeComplete(event = {}) {
    const node = String(event?.node || '').trim().toLowerCase();
    if (!node) return;

    const stepKey = resolveStepKeyByNode(node);
    const summary = String(event?.summary || '').trim() || `${resolveNodeLabel(node)} 已完成。`;
    const target = steps.value.find((item) => item.key === stepKey);
    if (!target) return;

    const cursorKey = `${stepKey}::${node}`;
    if (!runtimeNodeLogCursor.has(cursorKey)) {
      appendNodeLog(node, summary, 'done');
    } else {
      updateLatestNodeLog(stepKey, node, { detail: summary, status: 'done' });
    }

    if (STEP_FINAL_NODE[stepKey] === node) {
      setStepStatus(target.index, 'done', summary);
      if (stepKey === 'checkpoint') {
        setStepAction('checkpoint', null);
      }
      if (stepKey === 'insight') {
        setStepAction('insight', null);
        insightReportStreaming.value = false;
        insightReportReady.value = true;
      }
    } else {
      setStepStatus(target.index, 'running', summary);
    }

    if (node === 'search' || node === 'graph_build' || node === 'insight') {
      try {
        const snapshot = await getResearchSession(researchSessionId.value, {
          accessToken: accessTokenRef.value || ''
        });
        hydrateRuntimeArtifacts(snapshot || {});
      } catch {
        // keep websocket-driven states even if snapshot retrieval fails
      }
    }
  }

  function handleRuntimePause(event = {}) {
    const checkpoint = String(event?.checkpoint || '').trim().toLowerCase();
    if (checkpoint !== 'checkpoint_1' && checkpoint !== 'checkpoint_2') return;

    waitingResearchCheckpoint.value = checkpoint;
    const stepKey = checkpoint === 'checkpoint_2' ? 'insight' : 'checkpoint';
    const target = steps.value.find((item) => item.key === stepKey);
    if (!target) return;

    if (shouldAutoConfirmCheckpoint(checkpoint)) {
      const autoMessage = resolveAutoCheckpointDoneMessage(checkpoint);
      setStepStatus(target.index, 'done', autoMessage);
      appendStepLog(stepKey, {
        title: resolveNodeLabel(checkpoint),
        detail: autoMessage,
        status: 'done'
      });
      setStepAction(stepKey, null);
      runtimeAutoResumingCheckpoint.value = checkpoint;
      void continueAfterUnifiedCheckpoint(stepKey, { auto: true });
      return;
    }

    const message = String(event?.message || '').trim() || (
      checkpoint === 'checkpoint_2'
        ? '请先配置探索参数后继续执行。'
        : '等待确认后继续执行。'
    );
    if (checkpoint === 'checkpoint_2') {
      insightConfigSubmitting.value = false;
    }
    setStepStatus(target.index, 'action_required', message);
    appendStepLog(stepKey, {
      title: resolveNodeLabel(checkpoint),
      detail: message,
      status: 'doing'
    });
    setStepAction(stepKey, {
      label: checkpoint === 'checkpoint_2' ? '配置参数并开始探索' : '继续执行',
      disabled: checkpoint === 'checkpoint_2' ? Boolean(insightConfigSubmitting.value) : false
    });
  }

  function handleInsightStream(event = {}) {
    const section = String(event?.section || 'insight_markdown').trim().toLowerCase();
    if (section && section !== 'insight_markdown') return;

    const chunk = String(event?.chunk || '');
    const done = Boolean(event?.done);
    const accumulatedChars = Number(event?.accumulated_chars);
    const hasAccumulatedChars = Number.isFinite(accumulatedChars) && accumulatedChars >= 0;

    if (chunk) {
      if (!hasAccumulatedChars || accumulatedChars > insightStreamAccumulatedChars.value) {
        insightReportMarkdown.value = `${insightReportMarkdown.value}${chunk}`;
        insightStreamAccumulatedChars.value = hasAccumulatedChars
          ? Math.max(insightStreamAccumulatedChars.value, Math.round(accumulatedChars))
          : String(insightReportMarkdown.value || '').length;
      }
      markInsightStreamHeartbeat();
    }

    if (done) {
      insightReportStreaming.value = false;
      insightReportReady.value = Boolean(String(insightReportMarkdown.value || '').trim());
      markInsightStreamHeartbeat();
      if (insightReportReady.value) {
        setStepStatusByKey('insight', 'running', '探索报告已生成，等待流程完成收敛。');
      }
      return;
    }

    if (chunk) {
      insightReportStreaming.value = true;
      insightReportReady.value = false;
      setStepStatusByKey('insight', 'running', '正在流式生成探索报告...');
      return;
    }
  }

  function handleGraphStream(event = {}) {
    const stage = String(event?.stage || '').trim().toLowerCase();
    if (!stage) return;

    const stats = event?.stats && typeof event.stats === 'object' ? event.stats : {};
    const cursor = [
      stage,
      Number(stats?.selected_paper_count || 0),
      Number(stats?.node_count || 0),
      Number(stats?.edge_count || 0)
    ].join(':');
    if (graphStreamCursor.has(cursor)) return;
    graphStreamCursor.add(cursor);

    const streamSummary = String(event?.summary || '').trim();
    const streamQuery = String(
      event?.query
      || runtimeSeed.value?.input_value
      || seedRef.value?.input_value
      || ''
    ).trim();

    const streamPapers = Array.isArray(event?.papers) ? event.papers : [];
    if (streamPapers.length) {
      const previewGraph = buildRetrievalPreviewGraph(streamQuery, streamPapers);
      const previewSignature = `${buildPreviewGraphSignature(streamQuery, streamPapers)}#stream:${stage}`;
      commitGraphData(previewGraph, previewSignature);
      const detail = streamSummary || '首批关键论文已就绪，正在扩展图谱。';
      setStepStatusByKey('retrieve', 'running', detail);
      appendStepLog('retrieve', {
        title: 'Retriever Agent',
        detail,
        status: 'doing'
      });
      return;
    }

    const streamGraph = event?.graph && typeof event.graph === 'object' ? event.graph : null;
    if (!streamGraph || !Array.isArray(streamGraph?.nodes) || !Array.isArray(streamGraph?.edges)) return;
    const streamSignature = `${buildGraphSignature(streamGraph)}#stream:${stage}`;
    commitGraphData(streamGraph, streamSignature);
    if (stage === 'tier2') {
      const detail = streamSummary || '关键分支已加载，正在补全全量图谱。';
      setStepStatusByKey('graph', 'running', detail);
      appendStepLog('graph', {
        title: 'Graph Builder Agent',
        detail,
        status: 'doing'
      });
      return;
    }
    if (stage === 'tier3') {
      const detail = streamSummary || '全量图谱已加载，正在完成流程收敛。';
      setStepStatusByKey('graph', 'running', detail);
      appendStepLog('graph', {
        title: 'Graph Builder Agent',
        detail,
        status: 'doing'
      });
    }
  }

  function handleNegotiationRoundStarted(event = {}) {
    const taskKind = String(event?.task_kind || '').trim().toLowerCase();
    const stepKey = resolveStepKeyByTaskKind(taskKind);
    const round = normalizeNegotiationRound(event?.round);
    const taskLabel = resolveTaskKindLabel(taskKind);

    markEarlierStepsDone(stepKey);
    const { roundState } = ensureNegotiationRoundState({
      stepKey,
      event,
      defaultStatus: 'bidding'
    });

    roundState.status = 'bidding';
    roundState.updatedAt = resolveNegotiationTimestamp(event);

    setStepStatusByKey(stepKey, 'running', `协商中：正在为 ${taskLabel} 选择执行方案。`);
    appendStepLog(stepKey, {
      title: 'Coordinator Agent',
      detail: `第 ${round} 轮协商已启动：正在评估 ${taskLabel} 的执行候选。`,
      status: 'doing'
    });
  }

  function handleNegotiationBidReceived(event = {}) {
    const taskKind = String(event?.task_kind || '').trim().toLowerCase();
    const stepKey = resolveStepKeyByTaskKind(taskKind);

    markEarlierStepsDone(stepKey);
    const { roundState } = ensureNegotiationRoundState({
      stepKey,
      event,
      defaultStatus: 'bidding'
    });

    upsertNegotiationBid(roundState, buildNegotiationBid(event));
    if (!['awarded', 'vetoed', 'rebid'].includes(String(roundState.status || '').trim().toLowerCase())) {
      roundState.status = 'bidding';
    }
    roundState.updatedAt = resolveNegotiationTimestamp(event);

    const agentLabel = resolveAgentRuntimeLabel(event?.agent_id, event?.profile);
    const confidence = toFiniteNegotiationNumber(event?.confidence);
    const estimatedLatencyMs = toFiniteNegotiationNumber(event?.estimated_latency_ms);
    const estimatedCost = toFiniteNegotiationNumber(event?.estimated_cost);
    const confidenceText = Number.isFinite(confidence) && confidence > 0 ? confidence.toFixed(3) : '计算中';
    const latencyText = Number.isFinite(estimatedLatencyMs) && estimatedLatencyMs > 0
      ? `${Math.max(1, Math.round(estimatedLatencyMs))}ms`
      : '计算中';
    const costText = Number.isFinite(estimatedCost) && estimatedCost > 0 ? estimatedCost.toFixed(3) : '计算中';

    appendStepLog(stepKey, {
      title: 'Coordinator Agent',
      detail: `收到候选方案：${agentLabel}（置信度 ${confidenceText}，预计耗时 ${latencyText}，预计成本 ${costText}）。`,
      status: 'pending'
    });
  }

  function handleNegotiationContractAwarded(event = {}) {
    const taskKind = String(event?.task_kind || '').trim().toLowerCase();
    const stepKey = resolveStepKeyByTaskKind(taskKind);

    markEarlierStepsDone(stepKey);
    const { roundState } = ensureNegotiationRoundState({
      stepKey,
      event,
      defaultStatus: 'bidding'
    });

    assignNegotiationWinner(roundState, buildNegotiationBid(event));
    roundState.status = 'awarded';
    roundState.updatedAt = resolveNegotiationTimestamp(event);

    const agentLabel = resolveAgentRuntimeLabel(event?.agent_id, event?.profile);
    setStepStatusByKey(stepKey, 'running', `已确认执行方案：${agentLabel}。`);
    appendStepLog(stepKey, {
      title: 'Coordinator Agent',
      detail: `已授予执行合约：${agentLabel}。`,
      status: 'doing'
    });
  }

  function handleNegotiationBudgetUpdate(event = {}) {
    const taskKind = String(event?.task_kind || '').trim().toLowerCase();
    const stepKey = resolveStepKeyByTaskKind(taskKind);

    markEarlierStepsDone(stepKey);
    const stepState = ensureNegotiationStepState(stepKey);
    stepState.budget.spent = toFiniteNegotiationNumber(event?.spent);
    stepState.budget.limit = toFiniteNegotiationNumber(event?.limit);
    stepState.budget.remaining = toFiniteNegotiationNumber(event?.remaining);

    if (Number.isFinite(Number(event?.round))) {
      const { roundState } = ensureNegotiationRoundState({
        stepKey,
        event,
        defaultStatus: 'bidding'
      });
      roundState.updatedAt = resolveNegotiationTimestamp(event);
    }

    const safeTaskKind = String(event?.task_kind || '').trim().toLowerCase();
    if (safeTaskKind) {
      stepState.activeTaskKind = safeTaskKind;
    }

    const spent = Number(event?.spent);
    const limit = Number(event?.limit);
    const remaining = Number(event?.remaining);
    const spentText = Number.isFinite(spent) ? spent.toFixed(3) : '-';
    const limitText = Number.isFinite(limit) ? limit.toFixed(3) : '-';
    const remainingText = Number.isFinite(remaining) ? remaining.toFixed(3) : '-';

    appendStepLog(stepKey, {
      title: 'Coordinator Agent',
      detail: `预算更新：已使用 ${spentText} / ${limitText}，剩余 ${remainingText}。`,
      status: 'done'
    });
  }

  function handleNegotiationCriticVeto(event = {}) {
    const taskKind = String(event?.task_kind || '').trim().toLowerCase();
    const stepKey = resolveStepKeyByTaskKind(taskKind);
    const reason = String(event?.reason || '').trim() || '执行结果未通过质量审核。';

    markEarlierStepsDone(stepKey);
    const { roundState } = ensureNegotiationRoundState({
      stepKey,
      event,
      defaultStatus: 'bidding'
    });

    const vetoedAgentId = String(event?.agent_id || '').trim();
    const vetoedProfile = String(event?.profile || '').trim().toLowerCase();
    roundState.status = 'vetoed';
    roundState.veto = {
      reason,
      severity: String(event?.severity || '').trim().toLowerCase(),
      at: resolveNegotiationTimestamp(event)
    };
    roundState.updatedAt = resolveNegotiationTimestamp(event);

    if (vetoedAgentId) {
      let matched = false;
      for (const bid of roundState.bids) {
        const bidAgentId = String(bid?.agentId || '').trim();
        const bidProfile = String(bid?.profile || '').trim().toLowerCase();
        if (bidAgentId === vetoedAgentId && (!vetoedProfile || bidProfile === vetoedProfile)) {
          bid.status = 'vetoed';
          matched = true;
        } else if (String(bid?.status || '').trim().toLowerCase() === 'winner') {
          bid.status = 'bid';
        }
      }
      if (!matched) {
        roundState.bids.push({
          ...buildNegotiationBid(event),
          status: 'vetoed'
        });
      }
      if (roundState.winner && String(roundState.winner.agentId || '').trim() === vetoedAgentId) {
        roundState.winner.status = 'vetoed';
      }
    }

    setStepStatusByKey(stepKey, 'running', '质量审核未通过，准备重新协商执行方案。');
    appendStepLog(stepKey, {
      title: 'Quality SubAgent',
      detail: `审核结论：${reason}`,
      status: 'fallback'
    });
  }

  function handleNegotiationRebidScheduled(event = {}) {
    const taskKind = String(event?.task_kind || '').trim().toLowerCase();
    const stepKey = resolveStepKeyByTaskKind(taskKind);
    const retryCount = Number(event?.retry_count);
    const reason = String(event?.reason || '').trim();

    markEarlierStepsDone(stepKey);
    const { roundState } = ensureNegotiationRoundState({
      stepKey,
      event,
      defaultStatus: 'bidding'
    });

    roundState.status = 'rebid';
    roundState.rebid = {
      reason: reason || '正在重新发起竞标。',
      retryCount: Number.isFinite(retryCount) ? Math.max(1, Math.round(retryCount)) : null,
      at: resolveNegotiationTimestamp(event)
    };
    roundState.updatedAt = resolveNegotiationTimestamp(event);

    const retryText = Number.isFinite(retryCount) ? `第 ${Math.max(1, Math.round(retryCount))} 次重试` : '已触发重试';
    appendStepLog(stepKey, {
      title: 'Coordinator Agent',
      detail: `${retryText}：${reason || '正在重新发起竞标。'}`,
      status: 'doing'
    });
  }

  function handleNegotiationParallelShadowScheduled(event = {}) {
    const taskKind = String(event?.task_kind || '').trim().toLowerCase();
    const stepKey = resolveStepKeyByTaskKind(taskKind);
    const agentLabel = resolveAgentRuntimeLabel(event?.agent_id, event?.profile);
    appendStepLog(stepKey, {
      title: 'Coordinator Agent',
      detail: `并行候选已就绪：${agentLabel}。`,
      status: 'pending'
    });
  }

  function handleNegotiationCandidateFailed(event = {}) {
    const taskKind = String(event?.task_kind || '').trim().toLowerCase();
    const stepKey = resolveStepKeyByTaskKind(taskKind);
    const agentLabel = resolveAgentRuntimeLabel(event?.agent_id, event?.profile);
    const reason = String(event?.reason || '').trim() || '候选执行失败。';
    appendStepLog(stepKey, {
      title: 'Quality SubAgent',
      detail: `候选失败：${agentLabel}（${reason}）。`,
      status: 'fallback'
    });
  }

  function handleNegotiationParallelWinnerPromoted(event = {}) {
    const taskKind = String(event?.task_kind || '').trim().toLowerCase();
    const stepKey = resolveStepKeyByTaskKind(taskKind);
    const agentLabel = resolveAgentRuntimeLabel(event?.agent_id, event?.profile);
    setStepStatusByKey(stepKey, 'running', `并行评测已确认最优方案：${agentLabel}。`);
    appendStepLog(stepKey, {
      title: 'Coordinator Agent',
      detail: `并行结果切换：已采用 ${agentLabel} 的执行产物。`,
      status: 'done'
    });
  }

  function handleInsightOrchestratorEvent(event = {}) {
    markInsightStreamHeartbeat();
    const payload = event?.event && typeof event.event === 'object' ? event.event : {};
    const eventType = String(payload?.type || '').trim().toLowerCase();
    if (!eventType) return;
    const elapsedMs = Number(payload?.elapsed_ms);
    const elapsedText = Number.isFinite(elapsedMs) && elapsedMs >= 0
      ? `（耗时 ${Math.max(0, Math.round(elapsedMs))}ms）`
      : '';

    if (eventType === 'insight_report_compose_started') {
      insightReportStreaming.value = false;
      setStepStatusByKey('insight', 'running', '正在汇总并生成报告...');
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: '后处理阶段开始：正在汇总并生成报告正文。',
        status: 'doing'
      });
      return;
    }

    if (eventType === 'insight_progressive_draft_ready') {
      const draftChars = Number(payload?.draft_chars);
      const charsHint = Number.isFinite(draftChars) ? `（约 ${Math.max(0, Math.round(draftChars))} 字）` : '';
      setStepStatusByKey('insight', 'running', '首版草稿已生成，正在继续优化...');
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: `首版草稿已就绪${charsHint}，已优先输出可阅读内容。`,
        status: 'done'
      });
      return;
    }

    if (eventType === 'insight_report_compose_completed') {
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: `报告汇总完成${elapsedText}。`,
        status: 'done'
      });
      return;
    }

    if (eventType === 'insight_report_stream_started') {
      insightReportStreaming.value = true;
      markInsightStreamHeartbeat();
      setStepStatusByKey('insight', 'running', '正在实时生成报告内容...');
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: '开始流式输出报告正文。',
        status: 'doing'
      });
      return;
    }

    if (eventType === 'insight_report_stream_completed') {
      insightReportStreaming.value = false;
      markInsightStreamHeartbeat();
      insightReportReady.value = Boolean(String(insightReportMarkdown.value || '').trim());
      setStepStatusByKey('insight', 'running', '正文生成完成，正在保存报告文件...');
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: `报告流式输出完成${elapsedText}。`,
        status: 'done'
      });
      return;
    }

    if (eventType === 'insight_artifact_persist_started') {
      setStepStatusByKey('insight', 'running', '正在保存报告文件...');
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: '开始保存 Markdown/PDF 报告产物。',
        status: 'pending'
      });
      return;
    }

    if (eventType === 'insight_artifact_persist_completed') {
      const warning = String(payload?.warning || '').trim().toLowerCase();
      const markdownPath = String(payload?.markdown_path || '').trim();
      const pdfPath = String(payload?.pdf_path || '').trim();
      if (markdownPath) {
        insightReportReady.value = Boolean(String(insightReportMarkdown.value || '').trim());
      }
      if (warning) {
        setStepStatusByKey('insight', 'running', '报告已生成，PDF 降级为可选。');
        appendStepLog('insight', {
          title: 'Insight Orchestrator',
          detail: `报告保存完成${elapsedText}，但 PDF 生成降级（${warning}）。`,
          status: 'fallback'
        });
      } else {
        setStepStatusByKey('insight', 'running', '报告文件已保存，正在完成流程收敛...');
        appendStepLog('insight', {
          title: 'Insight Orchestrator',
          detail: `报告保存完成${elapsedText}（MD: ${markdownPath ? 'ok' : 'missing'}，PDF: ${pdfPath ? 'ok' : 'missing'}）。`,
          status: 'done'
        });
      }
      return;
    }

    if (eventType === 'insight_finalize_completed') {
      insightReportStreaming.value = false;
      insightReportReady.value = Boolean(String(insightReportMarkdown.value || '').trim());
      setStepStatusByKey('insight', 'running', '探索报告已生成，等待流程完成收敛。');
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: `报告后处理收敛完成${elapsedText}。`,
        status: 'done'
      });
      return;
    }

    if (eventType === 'insight_round_early_stopped') {
      const round = Number(payload?.round_index);
      const signalCount = Number(payload?.new_signal_count);
      const roundText = Number.isFinite(round) ? `第 ${Math.max(1, Math.round(round))} 轮后` : '当前轮次后';
      const signalText = Number.isFinite(signalCount)
        ? `，新增有效信号 ${Math.max(0, Math.round(signalCount))}`
        : '';
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: `${roundText}触发早停${signalText}，进入报告收敛阶段。`,
        status: 'fallback'
      });
      return;
    }

    if (eventType === 'insight_orchestrator_task_started') {
      const roleId = String(payload?.role_id || '').trim() || 'agent';
      const workerId = String(payload?.worker_id || '').trim() || '-';
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: `任务启动：${roleId}（worker: ${workerId}）`,
        status: 'doing'
      });
      return;
    }

    if (eventType === 'insight_orchestrator_task_finished') {
      const roleId = String(payload?.role_id || '').trim() || 'agent';
      const status = String(payload?.status || '').trim().toLowerCase() || 'completed';
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: `任务完成：${roleId}（状态：${status}）`,
        status: status === 'completed' ? 'done' : 'fallback'
      });
      return;
    }

    if (eventType === 'round_started') {
      const round = Number(payload?.round_index);
      const plannedTasks = Number(payload?.planned_tasks);
      const roundText = Number.isFinite(round) ? `第 ${Math.max(1, Math.round(round))} 轮` : '新一轮';
      const taskText = Number.isFinite(plannedTasks) ? `，计划任务 ${Math.max(0, Math.round(plannedTasks))} 个` : '';
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: `${roundText}开始${taskText}。`,
        status: 'pending'
      });
      return;
    }

    if (eventType === 'round_completed') {
      const round = Number(payload?.round_index);
      const completedTasks = Number(payload?.completed_tasks);
      const spawnedTasks = Number(payload?.spawned_tasks);
      const roundText = Number.isFinite(round) ? `第 ${Math.max(1, Math.round(round))} 轮` : '当前轮次';
      const completedText = Number.isFinite(completedTasks) ? `完成 ${Math.max(0, Math.round(completedTasks))}` : '完成 -';
      const spawnedText = Number.isFinite(spawnedTasks) ? `，子代理扩展 ${Math.max(0, Math.round(spawnedTasks))}` : '';
      appendStepLog('insight', {
        title: 'Insight Orchestrator',
        detail: `${roundText}结束：${completedText}${spawnedText}。`,
        status: 'done'
      });
    }
  }

  async function refreshRuntimeSnapshot({ finalize = false } = {}) {
    const sessionId = String(researchSessionId.value || '').trim();
    if (!sessionId) return null;

    const snapshot = await getResearchSession(sessionId, {
      accessToken: accessTokenRef.value || ''
    });

    hydrateRuntimeArtifacts(snapshot || {});
    reconcileInsightProgressFromSnapshot(snapshot || {});
    persistActiveRuntimeSessionSnapshot({
      session_id: sessionId,
      status: snapshot?.status,
      progress: snapshot?.progress,
      current_node: snapshot?.current_node,
      waiting_checkpoint: snapshot?.waiting_checkpoint,
      input_type: snapshot?.input_type,
      input_value: snapshot?.input_value,
      paper_range_years: snapshot?.paper_range_years,
      quick_mode: snapshot?.quick_mode
    });

    const status = String(snapshot?.status || '').trim().toLowerCase();
    if (status === 'completed') {
      finalizeAllRuntimeTraceStatuses();
      setStepStatusByKey('retrieve', 'done', steps.value.find((item) => item.key === 'retrieve')?.message || '论文检索完成。');
      setStepStatusByKey('checkpoint', 'done', steps.value.find((item) => item.key === 'checkpoint')?.message || '需求确认完成。');
      setStepStatusByKey('graph', 'done', steps.value.find((item) => item.key === 'graph')?.message || '知识图谱生成完成。');
      setStepStatusByKey('insight', 'done', steps.value.find((item) => item.key === 'insight')?.message || '探索与洞察完成。');
      setStepAction('checkpoint', null);
      setStepAction('insight', null);
      insightConfigSubmitting.value = false;
      insightReportStreaming.value = false;
      insightReportReady.value = Boolean(String(insightReportMarkdown.value || '').trim());
      normalizeNegotiationStateForCompletedWorkflow();
      ensureCompletedWorkflowStepLogs();
      persistCompletedWorkflowSnapshotFromState();
      waitingResearchCheckpoint.value = '';
      runtimeAutoResumingCheckpoint.value = '';
      graphLoading.value = false;
      unifiedRuntimeActive.value = false;
      stopInsightStreamWatchdog();
      clearActiveResearchSessionRecord();
      stopResearchPolling();
      closeResearchSocket();
      return snapshot;
    }

    if (finalize) {
      return snapshot;
    }

    if (status === 'failed') {
      const currentNode = String(snapshot?.current_node || '').trim().toLowerCase();
      const detail = Array.isArray(snapshot?.errors) && snapshot.errors.length
        ? String(snapshot.errors[snapshot.errors.length - 1] || '').trim()
        : '研究流程执行失败。';
      errorMessage.value = detail || '研究流程执行失败。';
      const stepKey = resolveFailureStepKey(errorMessage.value, currentNode, waitingResearchCheckpoint.value);
      setStepStatusByKey(stepKey, 'failed', errorMessage.value);
      appendFailureLog(stepKey, errorMessage.value);
      graphLoading.value = false;
      unifiedRuntimeActive.value = false;
      setStepAction('checkpoint', null);
      setStepAction('insight', null);
      insightConfigSubmitting.value = false;
      insightReportStreaming.value = false;
      stopInsightStreamWatchdog();
      clearActiveResearchSessionRecord();
      stopResearchPolling();
      closeResearchSocket();
      return snapshot;
    }

    if (status === 'stopped') {
      const step = steps.value.find((item) => String(item?.status || '').trim().toLowerCase() === 'running')
        || steps.value.find((item) => item.key === 'insight')
        || steps.value.find((item) => item.key === 'graph')
        || steps.value[0];
      if (step) {
        setStepStatus(step.index, 'failed', '流程已停止。');
      }
      graphLoading.value = false;
      unifiedRuntimeActive.value = false;
      runtimeAutoResumingCheckpoint.value = '';
      setStepAction('checkpoint', null);
      setStepAction('insight', null);
      insightConfigSubmitting.value = false;
      insightReportStreaming.value = false;
      stopInsightStreamWatchdog();
      clearActiveResearchSessionRecord();
      stopResearchPolling();
      closeResearchSocket();
      return snapshot;
    }

    const waiting = String(snapshot?.waiting_checkpoint || '').trim().toLowerCase();
    if (waiting) {
      waitingResearchCheckpoint.value = waiting;
      if (shouldAutoConfirmCheckpoint(waiting) && runtimeAutoResumingCheckpoint.value !== waiting) {
        runtimeAutoResumingCheckpoint.value = waiting;
        void continueAfterUnifiedCheckpoint('checkpoint', { auto: true });
      }
      if (waiting === 'checkpoint_1') {
        const target = steps.value.find((item) => item.key === 'checkpoint');
        if (target) {
          setStepStatus(target.index, 'done', resolveAutoCheckpointDoneMessage(waiting));
          setStepAction('checkpoint', null);
        }
      } else if (waiting === 'checkpoint_2') {
        const target = steps.value.find((item) => item.key === 'insight');
        if (target) {
          const message = '请先配置探索参数后继续执行。';
          setStepStatus(target.index, 'action_required', message);
          setStepAction('insight', {
            label: '配置参数并开始探索',
            disabled: Boolean(insightConfigSubmitting.value)
          });
        }
      }
    } else {
      waitingResearchCheckpoint.value = '';
      runtimeAutoResumingCheckpoint.value = '';
      const insightStep = steps.value.find((item) => item.key === 'insight');
      if (String(insightStep?.status || '').trim().toLowerCase() === 'action_required') {
        setStepAction('insight', null);
      }
    }

    return snapshot;
  }

  function startResearchPolling() {
    if (researchPollTimer || !researchSessionId.value) return;
    researchPollTimer = window.setInterval(() => {
      void refreshRuntimeSnapshot().catch(() => {
        // keep polling silently while runtime is active
      });
    }, 1400);
  }

  function handleRuntimeError(event = {}) {
    const message = String(event?.error || event?.message || '').trim() || '研究流程执行失败。';
    errorMessage.value = message;
    const fallbackStep = resolveFailureStepKey(
      message,
      String(event?.node || '').trim().toLowerCase(),
      waitingResearchCheckpoint.value
    );
    setStepStatusByKey(fallbackStep, 'failed', message);
    appendFailureLog(fallbackStep, message);
    graphLoading.value = false;
    unifiedRuntimeActive.value = false;
    setStepAction('checkpoint', null);
    setStepAction('insight', null);
    insightConfigSubmitting.value = false;
    insightReportStreaming.value = false;
    stopInsightStreamWatchdog();
    clearActiveResearchSessionRecord();
    stopResearchPolling();
    closeResearchSocket();
  }

  function handleRuntimeStopped() {
    const step = steps.value.find((item) => String(item?.status || '').trim().toLowerCase() === 'running')
      || steps.value.find((item) => item.key === 'insight')
      || steps.value.find((item) => item.key === 'graph')
      || steps.value[0];
    if (step) {
      setStepStatus(step.index, 'failed', '流程已停止。');
    }
    graphLoading.value = false;
    unifiedRuntimeActive.value = false;
    waitingResearchCheckpoint.value = '';
    setStepAction('checkpoint', null);
    setStepAction('insight', null);
    insightConfigSubmitting.value = false;
    insightReportStreaming.value = false;
    stopInsightStreamWatchdog();
    clearActiveResearchSessionRecord();
    stopResearchPolling();
    closeResearchSocket();
  }

  async function handleRuntimeEvent(event = {}) {
    const tsRaw = String(event?.ts || '').trim();
    if (tsRaw) {
      const parsedTs = Date.parse(tsRaw);
      if (Number.isFinite(parsedTs) && parsedTs > 0) {
        if (
          runtimeLastEventTsMs > 0
          && parsedTs + RUNTIME_EVENT_CLOCK_SKEW_MS < runtimeLastEventTsMs
        ) {
          return;
        }
        runtimeLastEventTsMs = Math.max(runtimeLastEventTsMs, parsedTs);
      }
    }

    const type = String(event?.type || '').trim().toLowerCase();
    if (!type) return;

    if (type === 'node_start') {
      handleRuntimeNodeStart(event);
      return;
    }
    if (type === 'thinking') {
      handleRuntimeThinking(event);
      return;
    }
    if (type === 'node_complete') {
      await handleRuntimeNodeComplete(event);
      return;
    }
    if (type === 'insight_stream') {
      handleInsightStream(event);
      return;
    }
    if (type === 'graph_stream') {
      handleGraphStream(event);
      return;
    }
    if (type === 'insight_orchestrator_event') {
      handleInsightOrchestratorEvent(event);
      return;
    }
    if (type === 'pause') {
      handleRuntimePause(event);
      return;
    }
    if (type === 'negotiation_round_started') {
      handleNegotiationRoundStarted(event);
      return;
    }
    if (type === 'negotiation_bid_received') {
      handleNegotiationBidReceived(event);
      return;
    }
    if (type === 'negotiation_contract_awarded') {
      handleNegotiationContractAwarded(event);
      return;
    }
    if (type === 'negotiation_budget_update') {
      handleNegotiationBudgetUpdate(event);
      return;
    }
    if (type === 'negotiation_critic_veto') {
      handleNegotiationCriticVeto(event);
      return;
    }
    if (type === 'negotiation_rebid_scheduled') {
      handleNegotiationRebidScheduled(event);
      return;
    }
    if (type === 'negotiation_parallel_shadow_scheduled') {
      handleNegotiationParallelShadowScheduled(event);
      return;
    }
    if (type === 'negotiation_candidate_failed') {
      handleNegotiationCandidateFailed(event);
      return;
    }
    if (type === 'negotiation_parallel_winner_promoted') {
      handleNegotiationParallelWinnerPromoted(event);
      return;
    }
    if (type === 'session_complete') {
      try {
        await refreshRuntimeSnapshot({ finalize: true });
      } catch {
        graphLoading.value = false;
        unifiedRuntimeActive.value = false;
      }
      return;
    }
    if (type === 'error') {
      handleRuntimeError(event);
      return;
    }
    if (type === 'stopped') {
      handleRuntimeStopped();
    }
  }

  function bindResearchSocket(sessionId) {
    closeResearchSocket();
    const token = String(accessTokenRef.value || '').trim();
    researchSocket = createResearchWebSocket(sessionId, token);

    researchSocket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        void handleRuntimeEvent(payload).catch(() => {
          // keep websocket session resilient to occasional event handling failures
        });
      } catch {
        // ignore malformed websocket events
      }
    };

    researchSocket.onerror = () => {
      if (!unifiedRuntimeActive.value) return;
      startResearchPolling();
    };

    researchSocket.onclose = () => {
      researchSocket = null;
      if (unifiedRuntimeActive.value) {
        startResearchPolling();
      }
    };
  }

  async function stopUnifiedRuntimeSession({ silent = true } = {}) {
    const sessionId = String(researchSessionId.value || '').trim();
    if (!sessionId || !unifiedRuntimeActive.value) {
      resetUnifiedRuntimeState();
      return;
    }

    try {
      await stopResearchSession(sessionId, { accessToken: accessTokenRef.value || '' });
    } catch {
      if (!silent) {
        errorMessage.value = '停止流程失败。';
      }
    } finally {
      resetUnifiedRuntimeState();
      graphLoading.value = false;
      clearActiveResearchSessionRecord();
    }
  }

  function markWorkflowTerminated(message = '流程已终止。') {
    const safeMessage = String(message || '').trim() || '流程已终止。';
    const runningStep = steps.value.find((item) => {
      const status = String(item?.status || '').trim().toLowerCase();
      return status === 'running' || status === 'action_required';
    });
    const targetStep = runningStep || activeStep.value || steps.value[0] || null;
    if (targetStep) {
      setStepStatus(targetStep.index, 'failed', safeMessage);
      appendFailureLog(targetStep.key, safeMessage);
    }
    setStepAction('checkpoint', null);
    setStepAction('insight', null);
    insightReportStreaming.value = false;
    waitingResearchCheckpoint.value = '';
    runtimeAutoResumingCheckpoint.value = '';
    errorMessage.value = safeMessage;
    graphLoading.value = false;
    unifiedRuntimeActive.value = false;
  }

  async function terminateWorkflow() {
    if (terminatingWorkflow.value || !canTerminateWorkflow.value) {
      return false;
    }

    terminatingWorkflow.value = true;
    try {
      const hasRuntimeSession = Boolean(String(researchSessionId.value || '').trim());
      if (hasRuntimeSession && unifiedRuntimeActive.value) {
        await stopUnifiedRuntimeSession({ silent: false });
      } else {
        stopResearchPolling();
        closeResearchSocket();
        resetUnifiedRuntimeState();
        graphLoading.value = false;
      }
      clearActiveResearchSessionRecord();
      markWorkflowTerminated('流程已终止。');
      return true;
    } catch (error) {
      errorMessage.value = String(error?.message || '').trim() || '终止流程失败。';
      return false;
    } finally {
      terminatingWorkflow.value = false;
      updateStepSignal();
    }
  }

  async function runUnifiedWorkflow(seed) {
    runtimeSeed.value = normalizeRuntimeSeed(seed || {});
    const payload = {
      input_type: runtimeSeed.value.input_type,
      input_value: runtimeSeed.value.input_value,
      paper_range_years: runtimeSeed.value.paper_range_years,
      quick_mode: runtimeSeed.value.quick_mode
    };

    const created = await startResearchSession(payload, { accessToken: accessTokenRef.value || '' });
    const sessionId = String(created?.session_id || '').trim();
    if (!sessionId) {
      throw new Error('research_session_missing');
    }

    unifiedRuntimeActive.value = true;
    researchSessionId.value = sessionId;
    waitingResearchCheckpoint.value = '';
    runtimeAutoResumingCheckpoint.value = '';

    persistActiveRuntimeSessionSnapshot({
      session_id: sessionId,
      status: 'running',
      input_type: runtimeSeed.value.input_type,
      input_value: runtimeSeed.value.input_value,
      paper_range_years: runtimeSeed.value.paper_range_years,
      quick_mode: runtimeSeed.value.quick_mode
    });

    setStepStatus(1, 'running', createRetrievalRunningMessage(runtimeSeed.value.input_type));
    setStepLogs('retrieve', []);
    bindResearchSocket(sessionId);
    startResearchPolling();
    startInsightStreamWatchdog();
    void refreshRuntimeSnapshot().catch(() => {
      // initial snapshot is optional; websocket events are primary
    });
  }

  async function attachUnifiedWorkflowSession(seed) {
    runtimeSeed.value = normalizeRuntimeSeed(seed || {});
    const sessionId = String(runtimeSeed.value.runtime_session_id || '').trim();
    if (!sessionId) {
      throw new Error('research_session_missing');
    }

    unifiedRuntimeActive.value = true;
    researchSessionId.value = sessionId;
    waitingResearchCheckpoint.value = '';
    runtimeAutoResumingCheckpoint.value = '';

    persistActiveRuntimeSessionSnapshot({
      session_id: sessionId,
      status: 'running',
      input_type: runtimeSeed.value.input_type,
      input_value: runtimeSeed.value.input_value,
      paper_range_years: runtimeSeed.value.paper_range_years,
      quick_mode: runtimeSeed.value.quick_mode
    });

    setStepStatus(1, 'running', '检测到已有进行中任务，正在恢复执行状态...');
    setStepLogs('retrieve', []);
    bindResearchSocket(sessionId);
    startResearchPolling();
    startInsightStreamWatchdog();
    void refreshRuntimeSnapshot().catch(() => {
      // keep websocket-driven recoveries resilient when snapshot fetch is transiently unavailable
    });
  }

  async function runGraphStage(context) {
    const {
      retrieval,
      retrievalQuery,
      inputType,
      seedInputValue,
      paperRangeYears
    } = context;

    setStepStatus(3, 'running', '正在生成知识图谱...');
    setStepLogs('graph', createRunningBuildLogs());

    const result = await buildKnowledgeGraph({
      query: retrievalQuery,
      max_papers: 24,
      max_entities_per_paper: 6,
      prefetched_papers: retrieval.papers || [],
      research_type: inputType || 'unknown',
      search_input: String(seedInputValue || '').trim(),
      search_range: formatSearchRangeLabel(inputType, paperRangeYears)
    }, accessTokenRef.value || '');

    let resolvedGraph = result;
    if (result.stored_in_neo4j) {
      try {
        resolvedGraph = await getKnowledgeGraph(result.graph_id);
      } catch {
        // keep real-time result when persisted copy cannot be loaded
      }
    }

    await playBuildTrace(result.build_steps || []);
    if (!Array.isArray(result.build_steps) || !result.build_steps.length) {
      setStepLogs('graph', createFallbackBuildLogs(result));
    }

    commitGraphData(resolvedGraph, buildGraphSignature(resolvedGraph));
    const panoramaStats = extractPanoramaStats(resolvedGraph || result || {});
    setStepStatus(
      3,
      'done',
      `知识图谱已生成，包含 ${panoramaStats.paperCount} 个论文节点、${panoramaStats.edgeCount} 条关联边。`
    );
  }

  async function runLegacyWorkflow() {
    if (graphLoading.value) return;
    resetSteps();
    errorMessage.value = '';
    graphLoading.value = true;

    const seed = seedRef.value || {};
    const inputType = String(seed?.input_type || 'domain').trim().toLowerCase();
    const quickMode = Boolean(seed?.quick_mode);

    try {
      setStepStatus(1, 'running', createRetrievalRunningMessage(inputType));
      setStepLogs('retrieve', createRunningRetrievalLogs(inputType));

      const paperRangeYears = parsePaperRangeYears(seed?.paper_range_years);
      const retrieval = await retrieveKnowledgePapers({
        query: seed.input_value,
        input_type: inputType,
        quick_mode: quickMode,
        paper_range_years: paperRangeYears,
        max_papers: 24
      });

      const retrievalQuery = String(retrieval?.query || seed.input_value).trim() || seed.input_value;
      await playRetrievalTrace(retrieval.steps || []);
      if (!Array.isArray(retrieval.steps) || !retrieval.steps.length) {
        setStepLogs('retrieve', createFallbackRetrievalLogs(retrieval));
      }

      const retrievalAuditLogs = createRetrievalAuditLogs(retrieval);
      if (retrievalAuditLogs.length) {
        const retrievalStep = steps.value.find((item) => item.key === 'retrieve');
        const existingLogs = Array.isArray(retrievalStep?.logs) ? retrievalStep.logs : [];
        setStepLogs('retrieve', [...existingLogs, ...retrievalAuditLogs]);
      }

      const selectedCount = Number(retrieval?.selected_count || 0);
      setStepStatus(1, 'done', `已筛选 ${selectedCount} 篇相关论文。`);
      const previewPapers = retrieval.papers || [];
      const previewSignature = buildPreviewGraphSignature(retrievalQuery, previewPapers);
      commitGraphData(buildRetrievalPreviewGraph(retrievalQuery, previewPapers), previewSignature);

      setStepStatus(2, 'done', '检索阶段已确认，自动进入知识图谱生成。');
      setStepLogs('checkpoint', [
        {
          title: 'Coordinator Agent',
          detail: `已自动继续：${formatSearchRangeLabel(inputType, paperRangeYears)}，${quickMode ? '快速模式' : '普通模式'}。`,
          status: 'done',
          statusText: toStatusText('done'),
          metaText: ''
        }
      ]);
      setStepAction('checkpoint', null);

      try {
        await runGraphStage({
          retrieval,
          retrievalQuery,
          inputType,
          seedInputValue: String(seed?.input_value || '').trim(),
          paperRangeYears
        });
        setStepStatus(4, 'skipped', '探索与洞察仅在新工作流运行时可用。');
      } catch (graphError) {
        errorMessage.value = graphError?.message || '知识图谱生成失败。';
        setStepStatus(3, 'failed', '知识图谱步骤失败。');
        appendFailureLog('graph', errorMessage.value);
      }
    } catch (error) {
      errorMessage.value = error?.message || '工作流执行失败。';
      setStepStatus(1, 'failed', '论文检索失败。');
      appendFailureLog('retrieve', errorMessage.value);
    } finally {
      graphLoading.value = false;
      updateStepSignal();
    }
  }

  async function resolveServerAuthoritativeRuntimeSeed(seed) {
    const fallbackSeed = normalizeRuntimeSeed(seed || {});
    const accessToken = String(accessTokenRef.value || '').trim();
    if (!accessToken) {
      return {
        checked: false,
        seed: null
      };
    }

    try {
      const active = await getActiveResearchSession({ accessToken });
      if (!active?.has_active_session || !active?.session) {
        clearActiveResearchSessionRecord();
        return {
          checked: true,
          seed: null
        };
      }

      const resolvedSeed = normalizeRuntimeSeedFromActiveSession(active.session, fallbackSeed);
      if (!resolvedSeed?.runtime_session_id) {
        clearActiveResearchSessionRecord();
        return {
          checked: true,
          seed: null
        };
      }

      clearCompletedWorkflowSnapshot();
      persistActiveResearchSessionRecord({
        session_id: resolvedSeed.runtime_session_id,
        status: String(active?.session?.status || 'running').trim().toLowerCase(),
        progress: Number(active?.session?.progress || 0),
        current_node: String(active?.session?.current_node || '').trim(),
        waiting_checkpoint: String(active?.session?.waiting_checkpoint || '').trim(),
        input_type: resolvedSeed.input_type,
        input_value: resolvedSeed.input_value,
        paper_range_years: resolvedSeed.paper_range_years,
        quick_mode: resolvedSeed.quick_mode
      });
      return {
        checked: true,
        seed: resolvedSeed
      };
    } catch {
      return {
        checked: false,
        seed: null
      };
    }
  }

  async function runWorkflow() {
    if (graphLoading.value) return;

    const requestedSeed = seedRef.value || {};
    const serverResolution = await resolveServerAuthoritativeRuntimeSeed(requestedSeed);
    const serverAuthoritativeSeed = serverResolution?.seed || null;
    let seed = serverAuthoritativeSeed || requestedSeed;
    if (serverResolution?.checked && !serverAuthoritativeSeed) {
      seed = {
        ...(seed || {}),
        runtime_session_id: ''
      };
    }
    const resumeSessionId = String(
      serverAuthoritativeSeed?.runtime_session_id
      || seed?.runtime_session_id
      || ''
    ).trim();
    if (unifiedRuntimeActive.value && !resumeSessionId) {
      await stopUnifiedRuntimeSession({ silent: true });
    } else {
      resetUnifiedRuntimeState();
    }

    resetSteps();
    errorMessage.value = '';

    if (!resumeSessionId && restoreCompletedWorkflowSnapshotFromStorage()) {
      return;
    }

    if (!resumeSessionId) {
      clearCompletedWorkflowSnapshot();
    }

    graphLoading.value = true;

    try {
      if (resumeSessionId) {
        await attachUnifiedWorkflowSession(seed);
      } else {
        await runUnifiedWorkflow(seed);
      }
      errorMessage.value = '';
    } catch (error) {
      resetUnifiedRuntimeState();
      if (shouldFallbackToLegacy(error)) {
        graphLoading.value = false;
        await runLegacyWorkflow();
        return;
      }

      const rawMessage = String(error?.message || '').trim();
      const activeSessionMatch = rawMessage.match(/^active_session_exists:([a-z0-9-]+)$/i);
      if (activeSessionMatch && activeSessionMatch[1]) {
        const activeSessionId = String(activeSessionMatch[1]).trim();
        persistActiveResearchSessionRecord({
          session_id: activeSessionId,
          status: 'running',
          input_type: String(seed?.input_type || 'domain').trim().toLowerCase(),
          input_value: String(seed?.input_value || '').trim(),
          paper_range_years: seed?.paper_range_years ?? null,
          quick_mode: Boolean(seed?.quick_mode)
        });
        errorMessage.value = '当前已有进行中的任务，请先恢复该任务或等待其完成。';
      } else {
        errorMessage.value = rawMessage || '研究流程启动失败。';
      }
      setStepStatus(1, 'failed', '研究流程启动失败。');
      appendFailureLog('retrieve', errorMessage.value);
      graphLoading.value = false;
    } finally {
      updateStepSignal();
    }
  }

  async function handleStepAction(stepKey) {
    const key = String(stepKey || '').trim().toLowerCase();
    if (key === 'checkpoint' && unifiedRuntimeActive.value) {
      await continueAfterUnifiedCheckpoint('checkpoint');
      return;
    }
    if (key === 'insight' && unifiedRuntimeActive.value) {
      const waiting = String(waitingResearchCheckpoint.value || '').trim().toLowerCase();
      if (waiting !== 'checkpoint_2') return;

      insightConfigSubmitting.value = true;
      setStepAction('insight', {
        label: '配置参数并开始探索',
        disabled: true
      });
      const config = {
        agent_count: Number.parseInt(
          normalizeInsightConfigValue(insightAgentCountDraft.value, {
            min: INSIGHT_AGENT_COUNT_MIN,
            max: INSIGHT_AGENT_COUNT_MAX,
            fallback: INSIGHT_AGENT_COUNT_DEFAULT
          }),
          10
        ),
        exploration_depth: Number.parseInt(
          normalizeInsightConfigValue(insightDepthDraft.value, {
            min: INSIGHT_DEPTH_MIN,
            max: INSIGHT_DEPTH_MAX,
            fallback: INSIGHT_DEPTH_DEFAULT
          }),
          10
        ),
        report_language: resolveReportLanguageFromLocale()
      };
      try {
        await continueAfterUnifiedCheckpoint('insight', { feedbackPayload: config });
      } finally {
        insightConfigSubmitting.value = false;
        if (String(waitingResearchCheckpoint.value || '').trim().toLowerCase() === 'checkpoint_2') {
          setStepAction('insight', {
            label: '配置参数并开始探索',
            disabled: false
          });
        }
      }
    }
  }

  function resolveReportSessionId() {
    const runtimeSession = String(researchSessionId.value || '').trim();
    if (runtimeSession) return runtimeSession;
    return String(runtimeSeed.value?.runtime_session_id || '').trim();
  }

  function resolveReportDownloadTitle() {
    const runtimeInputValue = String(runtimeSeed.value?.input_value || '').trim();
    if (runtimeInputValue) return runtimeInputValue;
    return String(seedRef.value?.input_value || '').trim();
  }

  async function downloadInsightMarkdown() {
    if (insightMarkdownDownloadLoading.value) return;
    const sessionId = resolveReportSessionId();
    const reportTitle = resolveReportDownloadTitle();
    if (!sessionId) {
      errorMessage.value = '报告会话不存在，无法下载。';
      return;
    }
    insightMarkdownDownloadLoading.value = true;
    try {
      await downloadResearchReport(sessionId, 'markdown', {
        accessToken: accessTokenRef.value || '',
        reportTitle
      });
    } catch (error) {
      errorMessage.value = String(error?.message || '').trim() || 'Markdown 下载失败。';
    } finally {
      insightMarkdownDownloadLoading.value = false;
    }
  }

  async function downloadInsightPdf() {
    if (insightPdfDownloadLoading.value) return;
    const sessionId = resolveReportSessionId();
    const reportTitle = resolveReportDownloadTitle();
    if (!sessionId) {
      errorMessage.value = '报告会话不存在，无法下载。';
      return;
    }
    insightPdfDownloadLoading.value = true;
    try {
      await downloadResearchReport(sessionId, 'pdf', {
        accessToken: accessTokenRef.value || '',
        reportTitle
      });
    } catch (error) {
      errorMessage.value = String(error?.message || '').trim() || 'PDF 下载失败。';
    } finally {
      insightPdfDownloadLoading.value = false;
    }
  }

  onUnmounted(() => {
    stopResearchPolling();
    stopInsightStreamWatchdog();
    closeResearchSocket();
  });

  return {
    steps,
    negotiationByStep,
    insightInlineConfig,
    graphLoading,
    canTerminateWorkflow,
    terminatingWorkflow,
    graphData,
    insightReportMarkdown,
    insightReportLanguage,
    insightReportReady,
    insightReportStreaming,
    hasInsightReport,
    insightMarkdownDownloadLoading,
    insightPdfDownloadLoading,
    errorMessage,
    graphStats,
    workflowProgress,
    currentTaskText,
    nextTaskText,
    activeStepHint,
    insightReportPlaceholderText,
    runWorkflow,
    terminateWorkflow,
    handleStepAction,
    updateInsightInlineConfig,
    downloadInsightMarkdown,
    downloadInsightPdf
  };
}
