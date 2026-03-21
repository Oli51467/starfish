import { computed, onUnmounted, ref, watch } from 'vue';

import {
  buildKnowledgeGraph,
  createResearchWebSocket,
  getKnowledgeGraph,
  getResearchSession,
  retrieveKnowledgePapers,
  resumeResearchSession,
  startResearchSession,
  stopResearchSession,
  updateResearchHistoryLineageStatus
} from '../api';
import { buildKnowledgeGraphSets } from '../components/graph/knowledgeGraphModel';
import { usePaperStore } from '../stores/paperStore';

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
      const paperId = toNodeId(paper?.paper_id, `preview-${index}`);
      return {
        id: `paper:${paperId}`,
        label: title,
        type: 'paper',
        score: Number(relevance.toFixed(3)),
        meta: {
          title,
          abstract: String(paper?.abstract || ''),
          year: String(paper?.year || ''),
          published_month: String(paper?.month || ''),
          citation_count: String(citationCount),
          venue: String(paper?.venue || ''),
          authors: Array.isArray(paper?.authors) ? paper.authors.join(', ') : '',
          url: String(paper?.url || ''),
          relevance: relevance.toFixed(3)
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

  return {
    query: safeQuery,
    title: `${safeQuery} 实时图谱预览`,
    nodes,
    edges
  };
}

function normalizeLineageSeedId(seedInputType, seedInputValue) {
  const inputType = String(seedInputType || '').trim().toLowerCase();
  let value = String(seedInputValue || '').trim();
  if (!value) return '';

  if (inputType === 'arxiv_id') {
    value = value.replace(/^arxiv:/i, '').trim();
    value = value.replace(/^https?:\/\/arxiv\.org\/(?:abs|pdf)\//i, '').trim();
    value = value.replace(/\.pdf$/i, '').trim();
    return value;
  }
  if (inputType === 'doi') {
    value = value.replace(/^doi:\s*/i, '').trim();
    value = value.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '').trim();
    return value;
  }
  return value;
}

function resolveLineageSeed({
  seedInputType,
  seedInputValue,
  retrieval,
  graphResult
}) {
  const normalizedInputType = String(seedInputType || '').trim().toLowerCase();
  const normalizedSeedId = normalizeLineageSeedId(normalizedInputType, seedInputValue);
  const papers = Array.isArray(retrieval?.papers) ? retrieval.papers : [];

  if ((normalizedInputType === 'arxiv_id' || normalizedInputType === 'doi') && normalizedSeedId) {
    const byRetrieval = papers.find((item) => String(item?.title || '').trim());
    return {
      paperId: normalizedSeedId,
      title: String(byRetrieval?.title || normalizedSeedId).trim()
    };
  }

  const byRetrieval = papers.find((item) => String(item?.paper_id || '').trim());
  if (byRetrieval) {
    return {
      paperId: String(byRetrieval.paper_id || '').trim(),
      title: String(byRetrieval.title || '').trim()
    };
  }

  const nodes = Array.isArray(graphResult?.nodes) ? graphResult.nodes : [];
  const byGraph = nodes.find((node) => {
    if (String(node?.type || '').toLowerCase() !== 'paper') return false;
    return Boolean(String(node?.paper_id || '').trim());
  });
  if (byGraph) {
    return {
      paperId: String(byGraph.paper_id || '').trim(),
      title: String(byGraph.label || '').trim()
    };
  }

  const fallback = normalizedSeedId || String(seedInputValue || '').trim();
  return {
    paperId: fallback,
    title: fallback
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
  parallel: 'Lineage Agent',
  checkpoint_2: 'Lineage Checkpoint'
};

const STEP_FLOW_ORDER = ['retrieve', 'checkpoint', 'graph', 'lineage'];
const STEP_FINAL_NODE = {
  retrieve: 'search',
  checkpoint: 'checkpoint_1',
  graph: 'graph_build',
  lineage: 'parallel'
};

function resolveStepKeyByNode(rawNode) {
  const node = String(rawNode || '').trim().toLowerCase();
  if (!node) return 'retrieve';
  if (node === 'checkpoint_1') return 'checkpoint';
  if (node === 'graph_build') return 'graph';
  if (['parallel', 'synthesizer', 'checkpoint_2', 'report', 'save'].includes(node)) return 'lineage';
  return 'retrieve';
}

function resolveNodeLabel(rawNode) {
  const node = String(rawNode || '').trim().toLowerCase();
  return RESEARCH_NODE_LABEL[node] || `Agent · ${node || 'unknown'}`;
}

export function usePaperWorkflow({
  seedRef,
  resultViewRef,
  accessTokenRef,
  onStepChange,
  onResultViewChange,
  onLineageAvailabilityChange
}) {
  const notifyStepChange = typeof onStepChange === 'function' ? onStepChange : () => {};
  const notifyResultViewChange = typeof onResultViewChange === 'function' ? onResultViewChange : () => {};
  const notifyLineageAvailability = typeof onLineageAvailabilityChange === 'function' ? onLineageAvailabilityChange : () => {};

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
      description: '确认当前检索范围与研究目标，再继续生成知识图谱。',
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
      key: 'lineage',
      title: '生成血缘树',
      description: '围绕起点论文展开祖先与后代演化脉络。',
      status: 'pending',
      message: '',
      logs: [],
      action: null
    }
  ]);

  const graphLoading = ref(false);
  const graphData = ref(null);
  const errorMessage = ref('');
  const lineageSeed = ref({ paperId: '', title: '' });
  const checkpointContext = ref(null);
  const researchSessionId = ref('');
  const unifiedRuntimeActive = ref(false);
  const waitingResearchCheckpoint = ref('');
  const runtimeAutoResumingCheckpoint = ref('');
  const lineageRevealApproved = ref(false);
  const pendingLineagePayload = ref(null);
  const graphSnapshotSignature = ref('');
  const runtimeSeed = ref({
    input_type: 'domain',
    input_value: '',
    paper_range_years: null,
    quick_mode: false,
    auto_lineage: false,
    lineage_seed_paper_id: ''
  });
  let researchSocket = null;
  let researchPollTimer = null;
  const runtimeNodeLogCursor = new Map();

  const {
    lineage: lineageData,
    lineageLoading,
    lineageErrorMessage,
    loadLineage,
    clearLineage
  } = usePaperStore();

  const canViewLineage = computed(() => Boolean(lineageLoading.value || lineageData.value));

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

  const activeViewKey = computed({
    get() {
      const normalized = String(resultViewRef.value || '').trim().toLowerCase();
      if (normalized === 'lineage' && !canViewLineage.value) return 'graph';
      return normalized === 'lineage' ? 'lineage' : 'graph';
    },
    set(nextView) {
      const normalized = String(nextView || '').trim().toLowerCase();
      if (normalized === 'lineage' && !canViewLineage.value) {
        notifyResultViewChange('graph');
        return;
      }
      notifyResultViewChange(normalized === 'lineage' ? 'lineage' : 'graph');
    }
  });

  const graphStats = computed(() => {
    const stats = extractPanoramaStats(graphData.value || {});
    return {
      nodeCount: stats.nodeCount,
      edgeCount: stats.edgeCount,
      directionCount: 0
    };
  });

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
    return '本轮流程已完成，可继续查看或切换结果视图。';
  });

  function updateStepSignal() {
    notifyStepChange({
      index: activeStep.value.index,
      total: steps.value.length,
      title: activeStep.value.title
    });
  }

  function setStepStatus(index, status, message = '') {
    const target = steps.value.find((item) => item.index === index);
    if (!target) return;
    target.status = status;
    target.message = message;
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
    if (!target) return;
    if (!Object.prototype.hasOwnProperty.call(target, 'action')) return;
    target.action = action || null;
  }

  function appendStepLog(stepKey, logItem) {
    const target = steps.value.find((item) => item.key === String(stepKey || '').trim());
    if (!target) return;
    const nextLog = {
      title: String(logItem?.title || '').trim() || '执行记录',
      detail: String(logItem?.detail || '').trim() || '工作流运行中。',
      status: String(logItem?.status || 'pending').trim() || 'pending',
      statusText: toStatusText(logItem?.status || 'pending'),
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
    target.logs = [...(Array.isArray(target.logs) ? target.logs : []), nextLog];
  }

  function updateLatestNodeLog(stepKey, node, patch = {}) {
    const cursorKey = `${String(stepKey || '').trim()}::${String(node || '').trim()}`;
    const logIndex = runtimeNodeLogCursor.get(cursorKey);
    if (!Number.isInteger(logIndex)) return;
    const target = steps.value.find((item) => item.key === String(stepKey || '').trim());
    if (!target || !Array.isArray(target.logs) || !target.logs[logIndex]) return;

    const nextStatus = String(patch?.status || target.logs[logIndex].status || 'pending');
    target.logs[logIndex] = {
      ...target.logs[logIndex],
      ...patch,
      status: nextStatus,
      statusText: toStatusText(nextStatus)
    };
  }

  function appendNodeLog(node, detail, status = 'doing') {
    const stepKey = resolveStepKeyByNode(node);
    const title = resolveNodeLabel(node);
    const target = steps.value.find((item) => item.key === stepKey);
    if (!target) return;
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

  function resetUnifiedRuntimeState() {
    stopResearchPolling();
    closeResearchSocket();
    researchSessionId.value = '';
    unifiedRuntimeActive.value = false;
    waitingResearchCheckpoint.value = '';
    runtimeAutoResumingCheckpoint.value = '';
    lineageRevealApproved.value = false;
    pendingLineagePayload.value = null;
    graphSnapshotSignature.value = '';
    runtimeNodeLogCursor.clear();
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

  function resetSteps() {
    runtimeNodeLogCursor.clear();
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

  function resetLineageState() {
    clearLineage();
    lineageSeed.value = { paperId: '', title: '' };
    pendingLineagePayload.value = null;
    graphSnapshotSignature.value = '';
    activeViewKey.value = 'graph';
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

  function normalizeRuntimeSeed(seed = {}) {
    return {
      input_type: String(seed?.input_type || 'domain').trim().toLowerCase() === 'domain'
        ? 'domain'
        : (String(seed?.input_type || '').trim().toLowerCase() === 'doi' ? 'doi' : 'arxiv_id'),
      input_value: String(seed?.input_value || '').trim(),
      paper_range_years: parsePaperRangeYears(seed?.paper_range_years),
      quick_mode: Boolean(seed?.quick_mode),
      auto_lineage: Boolean(seed?.auto_lineage),
      lineage_seed_paper_id: String(seed?.lineage_seed_paper_id || '').trim()
    };
  }

  function shouldFallbackToLegacy(error) {
    const message = String(error?.message || '').trim().toLowerCase();
    if (!message) return false;
    if (message.includes('403') || message.includes('401') || message.includes('forbidden')) {
      return false;
    }
    return (
      message.includes('404')
      || message.includes('session_not_found')
      || message.includes('/api/research')
      || message.includes('not found')
      || message.includes('connection')
    );
  }

  function resolveCheckpointStepKey(checkpointNode) {
    const normalized = String(checkpointNode || '').trim().toLowerCase();
    if (normalized === 'checkpoint_1') return 'checkpoint';
    if (normalized === 'checkpoint_2') return 'lineage';
    return '';
  }

  function resolveCheckpointActionLabel(checkpointNode) {
    const normalized = String(checkpointNode || '').trim().toLowerCase();
    if (normalized === 'checkpoint_2') {
      return '确认生成血缘树';
    }
    return '确认需求并继续';
  }

  function shouldAutoConfirmCheckpoint(checkpointNode) {
    const normalized = String(checkpointNode || '').trim().toLowerCase();
    return normalized === 'checkpoint_1';
  }

  function shouldAutoRevealLineageView() {
    return lineageRevealApproved.value;
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
      }
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
    if (nextSignature && nextSignature === graphSnapshotSignature.value) {
      return false;
    }
    graphData.value = nextGraph;
    graphSnapshotSignature.value = nextSignature;
    return true;
  }

  function hydrateLineageSeedFromRuntimeSnapshot(snapshot = {}) {
    const retrieval = { papers: Array.isArray(snapshot?.papers) ? snapshot.papers : [] };
    const graphResult = snapshot?.graph && typeof snapshot.graph === 'object'
      ? snapshot.graph
      : graphData.value;
    const seedPaper = resolveLineageSeed({
      seedInputType: snapshot?.input_type || runtimeSeed.value.input_type,
      seedInputValue: snapshot?.input_value || runtimeSeed.value.input_value,
      retrieval,
      graphResult
    });

    const preferredLineageSeedPaperId = String(runtimeSeed.value.lineage_seed_paper_id || '').trim();
    if (preferredLineageSeedPaperId) {
      const preferredPaper = retrieval.papers.find(
        (item) => String(item?.paper_id || '').trim() === preferredLineageSeedPaperId
      );
      seedPaper.paperId = preferredLineageSeedPaperId;
      seedPaper.title = String(preferredPaper?.title || seedPaper.title || preferredLineageSeedPaperId).trim();
    }
    lineageSeed.value = seedPaper;
  }

  function hydrateRuntimeArtifacts(snapshot = {}) {
    if (snapshot?.graph && typeof snapshot.graph === 'object') {
      commitGraphData(snapshot.graph, buildGraphSignature(snapshot.graph));
    } else if (Array.isArray(snapshot?.papers) && snapshot.papers.length) {
      const previewQuery = snapshot?.research_goal || snapshot?.input_value || runtimeSeed.value.input_value;
      const previewSignature = buildPreviewGraphSignature(previewQuery, snapshot.papers);
      const previewGraph = buildRetrievalPreviewGraph(previewQuery, snapshot.papers);
      commitGraphData(previewGraph, previewSignature);
    }

    if (snapshot?.lineage && typeof snapshot.lineage === 'object') {
      pendingLineagePayload.value = snapshot.lineage;
      if (lineageRevealApproved.value) {
        lineageData.value = snapshot.lineage;
        lineageErrorMessage.value = '';
        if (shouldAutoRevealLineageView()) {
          activeViewKey.value = 'lineage';
        }
      }
    }

    if (Array.isArray(snapshot?.papers) && snapshot.papers.length) {
      hydrateLineageSeedFromRuntimeSnapshot(snapshot);
    }
  }

  function handleRuntimeNodeStart(event = {}) {
    const node = String(event?.node || '').trim().toLowerCase();
    if (!node) return;
    const stepKey = resolveStepKeyByNode(node);
    const step = steps.value.find((item) => item.key === stepKey);
    if (!step) return;

    markEarlierStepsDone(stepKey);
    const runningMessage = node === 'parallel'
      ? '正在生成血缘树...'
      : `正在执行 ${resolveNodeLabel(node)}。`;
    setStepStatus(step.index, 'running', runningMessage);
    appendNodeLog(node, runningMessage, 'doing');
    if (node === 'graph_build') {
      void refreshRuntimeSnapshot().catch(() => {
        // keep graph-building stage resilient when snapshot fetch is transiently unavailable
      });
    }
    setStepAction('checkpoint', null);
    if (node !== 'checkpoint_2') {
      setStepAction('lineage', null);
    }
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
    } else {
      setStepStatus(target.index, 'running', summary);
    }

    if (node === 'search' || node === 'graph_build' || node === 'parallel') {
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
    const stepKey = resolveCheckpointStepKey(checkpoint);
    if (!stepKey) return;
    waitingResearchCheckpoint.value = checkpoint;
    const message = String(event?.message || '').trim() || '等待确认后继续执行。';
    const target = steps.value.find((item) => item.key === stepKey);
    if (!target) return;

    if (shouldAutoConfirmCheckpoint(checkpoint)) {
      const autoMessage = '知识图谱已生成，系统将自动继续后续分析。';
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

    let actionMessage = message;
    if (checkpoint === 'checkpoint_2') {
      actionMessage = '知识图谱已完成，请确认是否生成并展示血缘树。';
    }
    setStepStatus(target.index, 'action_required', actionMessage);
    appendStepLog(stepKey, {
      title: resolveNodeLabel(checkpoint),
      detail: actionMessage,
      status: 'doing'
    });
    setStepAction(stepKey, {
      label: resolveCheckpointActionLabel(checkpoint),
      disabled: false
    });
  }

  async function refreshRuntimeSnapshot({ finalize = false } = {}) {
    const sessionId = String(researchSessionId.value || '').trim();
    if (!sessionId) return null;
    const snapshot = await getResearchSession(sessionId, {
      accessToken: accessTokenRef.value || ''
    });
    hydrateRuntimeArtifacts(snapshot || {});

    const status = String(snapshot?.status || '').trim().toLowerCase();
    if (status === 'completed') {
      finalizeAllRuntimeTraceStatuses();
      setStepStatusByKey('retrieve', 'done', steps.value.find((item) => item.key === 'retrieve')?.message || '论文检索完成。');
      setStepStatusByKey('checkpoint', 'done', steps.value.find((item) => item.key === 'checkpoint')?.message || '检查点确认完成。');
      setStepStatusByKey('graph', 'done', steps.value.find((item) => item.key === 'graph')?.message || '知识图谱生成完成。');
      const lineagePayload = snapshot?.lineage && typeof snapshot.lineage === 'object' ? snapshot.lineage : null;
      const ancestors = Array.isArray(lineagePayload?.ancestors) ? lineagePayload.ancestors.length : 0;
      const descendants = Array.isArray(lineagePayload?.descendants) ? lineagePayload.descendants.length : 0;
      const lineageCount = ancestors + descendants;
      if (lineagePayload) {
        setStepStatusByKey(
          'lineage',
          'done',
          lineageCount > 0 ? `血缘树已生成，关联论文 ${lineageCount} 篇。` : '血缘树已生成。'
        );
      } else {
        setStepStatusByKey('lineage', 'failed', '血缘树未生成成功，请重试。');
        appendFailureLog('lineage', '本次未产出可展示的血缘树结果。');
      }
      setStepAction('checkpoint', null);
      setStepAction('lineage', lineagePayload ? null : {
        label: '重新生成血缘树',
        disabled: false
      });
      waitingResearchCheckpoint.value = '';
      runtimeAutoResumingCheckpoint.value = '';
      graphLoading.value = false;
      unifiedRuntimeActive.value = false;
      stopResearchPolling();
      closeResearchSocket();
      return snapshot;
    }

    if (finalize) {
      return snapshot;
    }

    if (status === 'failed') {
      const currentNode = String(snapshot?.current_node || '').trim().toLowerCase();
      const stepKey = resolveStepKeyByNode(currentNode);
      const detail = Array.isArray(snapshot?.errors) && snapshot.errors.length
        ? String(snapshot.errors[snapshot.errors.length - 1] || '').trim()
        : '研究流程执行失败。';
      errorMessage.value = detail || '研究流程执行失败。';
      setStepStatusByKey(stepKey, 'failed', errorMessage.value);
      appendFailureLog(stepKey, errorMessage.value);
      graphLoading.value = false;
      unifiedRuntimeActive.value = false;
      stopResearchPolling();
      closeResearchSocket();
      return snapshot;
    }

    if (status === 'stopped') {
      setStepStatusByKey('lineage', 'failed', '流程已停止。');
      graphLoading.value = false;
      unifiedRuntimeActive.value = false;
      runtimeAutoResumingCheckpoint.value = '';
      stopResearchPolling();
      closeResearchSocket();
      return snapshot;
    }

    const waiting = String(snapshot?.waiting_checkpoint || '').trim().toLowerCase();
    if (waiting) {
      waitingResearchCheckpoint.value = waiting;
      if (shouldAutoConfirmCheckpoint(waiting) && runtimeAutoResumingCheckpoint.value !== waiting) {
        runtimeAutoResumingCheckpoint.value = waiting;
        void continueAfterUnifiedCheckpoint(resolveCheckpointStepKey(waiting), { auto: true });
      }
      const stepKey = resolveCheckpointStepKey(waiting);
      const target = steps.value.find((item) => item.key === stepKey);
      if (target) {
        if (shouldAutoConfirmCheckpoint(waiting)) {
          setStepStatus(target.index, 'done', '知识图谱已生成，系统自动继续后续分析。');
          setStepAction(stepKey, null);
        } else {
          const actionMessage = waiting === 'checkpoint_2'
            ? '知识图谱已完成，请确认是否生成并展示血缘树。'
            : '等待确认后继续执行。';
          setStepStatus(target.index, 'action_required', actionMessage);
          setStepAction(stepKey, {
            label: resolveCheckpointActionLabel(waiting),
            disabled: false
          });
        }
      }
    } else {
      runtimeAutoResumingCheckpoint.value = '';
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
    const checkpointStep = resolveCheckpointStepKey(waitingResearchCheckpoint.value);
    const fallbackStep = checkpointStep || resolveStepKeyByNode(event?.node || 'lineage');
    setStepStatusByKey(fallbackStep, 'failed', message);
    appendFailureLog(fallbackStep, message);
    graphLoading.value = false;
    unifiedRuntimeActive.value = false;
    stopResearchPolling();
    closeResearchSocket();
  }

  function handleRuntimeStopped() {
    setStepStatusByKey('lineage', 'failed', '流程已停止。');
    graphLoading.value = false;
    unifiedRuntimeActive.value = false;
    waitingResearchCheckpoint.value = '';
    stopResearchPolling();
    closeResearchSocket();
  }

  async function handleRuntimeEvent(event = {}) {
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
    if (type === 'pause') {
      handleRuntimePause(event);
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

  async function continueAfterUnifiedCheckpoint(stepKey, options = {}) {
    const auto = Boolean(options?.auto);
    const safeStepKey = String(stepKey || '').trim();
    const checkpoint = String(waitingResearchCheckpoint.value || '').trim().toLowerCase();
    if (!safeStepKey || !checkpoint) return;
    if (resolveCheckpointStepKey(checkpoint) !== safeStepKey) return;
    const sessionId = String(researchSessionId.value || '').trim();
    if (!sessionId) return;

    if (!auto) {
      setStepAction(safeStepKey, {
        label: resolveCheckpointActionLabel(checkpoint),
        disabled: true
      });
    }

    try {
      const result = await resumeResearchSession(
        sessionId,
        '',
        { accessToken: accessTokenRef.value || '' }
      );
      if (!result?.resumed) {
        if (!auto) {
          setStepAction(safeStepKey, {
            label: resolveCheckpointActionLabel(checkpoint),
            disabled: false
          });
        } else {
          const target = steps.value.find((item) => item.key === safeStepKey);
          if (target) {
            setStepStatus(target.index, 'action_required', '自动继续失败，请手动确认后继续。');
          }
          setStepAction(safeStepKey, {
            label: resolveCheckpointActionLabel(checkpoint),
            disabled: false
          });
        }
        return;
      }
      waitingResearchCheckpoint.value = '';
      runtimeAutoResumingCheckpoint.value = '';
      if (checkpoint === 'checkpoint_2') {
        lineageRevealApproved.value = true;
        if (pendingLineagePayload.value && typeof pendingLineagePayload.value === 'object') {
          lineageData.value = pendingLineagePayload.value;
          lineageErrorMessage.value = '';
        }
        if (lineageData.value) {
          activeViewKey.value = 'lineage';
        }
      }
      const target = steps.value.find((item) => item.key === safeStepKey);
      if (target) {
        if (auto && safeStepKey === 'checkpoint') {
          setStepStatus(target.index, 'done', '知识图谱已生成，系统自动继续后续分析。');
        } else if (checkpoint === 'checkpoint_2') {
          setStepStatus(target.index, 'running', '已确认，正在生成血缘树...');
          appendStepLog('lineage', {
            title: resolveNodeLabel('parallel'),
            detail: '正在生成血缘树...',
            status: 'doing'
          });
        } else {
          setStepStatus(
            target.index,
            'running',
            auto ? '已自动确认，正在继续执行。' : '已确认，正在继续执行。'
          );
        }
      }
    } catch (error) {
      const message = error?.message || '继续执行失败。';
      errorMessage.value = message;
      runtimeAutoResumingCheckpoint.value = '';
      if (!auto) {
        setStepAction(safeStepKey, {
          label: resolveCheckpointActionLabel(checkpoint),
          disabled: false
        });
      } else {
        const target = steps.value.find((item) => item.key === safeStepKey);
        if (target) {
          setStepStatus(target.index, 'action_required', '自动继续失败，请手动确认后继续。');
        }
        setStepAction(safeStepKey, {
          label: resolveCheckpointActionLabel(checkpoint),
          disabled: false
        });
      }
    }
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
    lineageRevealApproved.value = false;

    setStepStatus(1, 'running', createRetrievalRunningMessage(runtimeSeed.value.input_type));
    setStepLogs('retrieve', []);
    bindResearchSocket(sessionId);
    startResearchPolling();
    void refreshRuntimeSnapshot().catch(() => {
      // initial snapshot is optional; websocket events are the primary source
    });
  }

  async function finalizeLineageSetup({
    inputType,
    seedInputValue,
    retrieval,
    graphResult,
    preferredLineageSeedPaperId,
    shouldAutoGenerateLineage
  }) {
    const seedPaper = resolveLineageSeed({
      seedInputType: inputType,
      seedInputValue,
      retrieval,
      graphResult
    });
    if (preferredLineageSeedPaperId) {
      const papers = Array.isArray(retrieval?.papers) ? retrieval.papers : [];
      const preferredPaper = papers.find((item) => String(item?.paper_id || '').trim() === preferredLineageSeedPaperId);
      seedPaper.paperId = preferredLineageSeedPaperId;
      if (preferredPaper?.title) {
        seedPaper.title = String(preferredPaper.title || '').trim();
      } else if (!String(seedPaper.title || '').trim()) {
        seedPaper.title = preferredLineageSeedPaperId;
      }
    }

    lineageSeed.value = seedPaper;
    setStepStatus(4, 'action_required', `已定位血缘树起点论文：${seedPaper.title || seedPaper.paperId || '未命名论文'}。`);
    setStepLogs('lineage', [
      {
        title: '起点论文确认',
        detail: '已确认本次血缘树起点论文，可继续生成。',
        status: 'done',
        statusText: toStatusText('done'),
        metaText: ''
      }
    ]);
    setStepAction('lineage', {
      label: '生成血缘树',
      disabled: false
    });
    if (shouldAutoGenerateLineage) {
      await generateLineageTree();
    }
  }

  async function runGraphStage(context) {
    const {
      retrieval,
      retrievalQuery,
      inputType,
      seedInputValue,
      paperRangeYears,
      preferredLineageSeedPaperId,
      shouldAutoGenerateLineage
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

    await finalizeLineageSetup({
      inputType,
      seedInputValue,
      retrieval,
      graphResult: resolvedGraph || result,
      preferredLineageSeedPaperId,
      shouldAutoGenerateLineage
    });
  }

  async function continueAfterLegacyCheckpoint() {
    if (graphLoading.value) return;
    const context = checkpointContext.value;
    if (!context) return;

    setStepAction('checkpoint', {
      label: '确认需求并继续',
      disabled: true
    });
    const checkpointLogs = Array.isArray(steps.value.find((item) => item.key === 'checkpoint')?.logs)
      ? [...(steps.value.find((item) => item.key === 'checkpoint')?.logs || [])]
      : [];
    if (checkpointLogs.length) {
      const lastIndex = checkpointLogs.length - 1;
      checkpointLogs[lastIndex] = {
        ...checkpointLogs[lastIndex],
        detail: '已确认需求，进入知识图谱生成阶段。',
        status: 'done',
        statusText: toStatusText('done')
      };
      setStepLogs('checkpoint', checkpointLogs);
    }
    setStepStatus(2, 'done', '需求已确认，开始生成知识图谱。');
    setStepAction('checkpoint', null);
    checkpointContext.value = null;

    graphLoading.value = true;
    try {
      await runGraphStage(context);
      errorMessage.value = '';
    } catch (error) {
      errorMessage.value = error?.message || '知识图谱生成失败。';
      setStepStatus(3, 'failed', '知识图谱步骤失败。');
      appendFailureLog('graph', errorMessage.value);

      if (context?.shouldAutoGenerateLineage && context?.preferredLineageSeedPaperId) {
        lineageSeed.value = {
          paperId: context.preferredLineageSeedPaperId,
          title: context.preferredLineageSeedPaperId
        };
        setStepStatus(4, 'running', '知识图谱步骤失败，正在直接生成血缘树...');
        setStepLogs('lineage', [
          {
            title: '降级处理',
            detail: '已跳过图谱展示，直接尝试生成血缘树。',
            status: 'fallback',
            statusText: toStatusText('fallback'),
            metaText: ''
          }
        ]);
        await generateLineageTree();
        if (lineageData.value) {
          errorMessage.value = '';
        }
      }
    } finally {
      graphLoading.value = false;
      updateStepSignal();
    }
  }

  async function runLegacyWorkflow() {
    if (graphLoading.value) return;
    resetSteps();
    resetLineageState();
    checkpointContext.value = null;
    errorMessage.value = '';
    graphLoading.value = true;

    const seed = seedRef.value || {};
    const inputType = String(seed?.input_type || 'domain').trim().toLowerCase();
    const quickMode = Boolean(seed?.quick_mode);
    const preferredLineageSeedPaperId = String(seed?.lineage_seed_paper_id || '').trim();
    const shouldAutoGenerateLineage = false;

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

      setStepStatus(2, 'done', '知识图谱生成阶段将自动继续。');
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
      checkpointContext.value = null;
      try {
        await runGraphStage({
          retrieval,
          retrievalQuery,
          inputType,
          seedInputValue: String(seed?.input_value || '').trim(),
          paperRangeYears,
          preferredLineageSeedPaperId,
          shouldAutoGenerateLineage
        });
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

  async function runWorkflow() {
    if (graphLoading.value) return;

    await stopUnifiedRuntimeSession({ silent: true });
    resetSteps();
    resetLineageState();
    checkpointContext.value = null;
    errorMessage.value = '';
    graphLoading.value = true;

    const seed = seedRef.value || {};
    try {
      await runUnifiedWorkflow(seed);
      errorMessage.value = '';
    } catch (error) {
      resetUnifiedRuntimeState();
      if (shouldFallbackToLegacy(error)) {
        graphLoading.value = false;
        await runLegacyWorkflow();
        return;
      }
      errorMessage.value = error?.message || '研究流程启动失败。';
      setStepStatus(1, 'failed', '研究流程启动失败。');
      appendFailureLog('retrieve', errorMessage.value);
      graphLoading.value = false;
    } finally {
      updateStepSignal();
    }
  }

  async function generateLineageTree() {
    const seedPaperId = String(lineageSeed.value?.paperId || '').trim();
    if (!seedPaperId || lineageLoading.value) return;

    const lineageLogs = [];
    const pushLineageLog = ({
      title,
      detail,
      status = 'pending',
      metaText = ''
    }) => {
      lineageLogs.push({
        title: String(title || '').trim() || '血缘树处理',
        detail: String(detail || '').trim(),
        status,
        statusText: toStatusText(status),
        metaText: String(metaText || '').trim()
      });
      setStepLogs('lineage', [...lineageLogs]);
      return lineageLogs.length - 1;
    };
    const updateLineageLog = (index, patch = {}) => {
      if (!Number.isInteger(index) || index < 0 || index >= lineageLogs.length) return;
      const nextStatus = patch.status || lineageLogs[index].status || 'pending';
      lineageLogs[index] = {
        ...lineageLogs[index],
        ...patch,
        status: nextStatus,
        statusText: toStatusText(nextStatus),
        metaText: String(patch.metaText ?? lineageLogs[index].metaText ?? '').trim()
      };
      setStepLogs('lineage', [...lineageLogs]);
    };

    setStepStatus(4, 'running', '正在生成血缘树...');
    pushLineageLog({
      title: '起点论文确认',
      detail: '已确认起点论文，开始构建血缘脉络。',
      status: 'done'
    });
    const requestLogIndex = pushLineageLog({
      title: '扩展引用脉络',
      detail: '正在扩展祖先与后代论文关系...',
      status: 'doing'
    });
    setStepAction('lineage', {
      label: '生成血缘树',
      disabled: true
    });

    const payload = await loadLineage(seedPaperId, {
      ancestorDepth: 2,
      descendantDepth: 2,
      forceRefresh: true
    });

    if (!payload) {
      updateLineageLog(requestLogIndex, {
        detail: lineageErrorMessage.value || '生成血缘树失败。',
        status: 'fallback',
        metaText: ''
      });
      pushLineageLog({
        title: '执行中断',
        detail: '本次血缘树生成失败，可重新发起。',
        status: 'fallback'
      });
      setStepStatus(4, 'failed', lineageErrorMessage.value || '生成血缘树失败。');
      setStepAction('lineage', {
        label: '重新生成血缘树',
        disabled: false
      });
      return;
    }

    activeViewKey.value = 'lineage';
    const ancestors = Array.isArray(payload?.ancestors) ? payload.ancestors.length : 0;
    const descendants = Array.isArray(payload?.descendants) ? payload.descendants.length : 0;
    updateLineageLog(requestLogIndex, {
      detail: `引用网络构建完成，祖先 ${ancestors} 篇，后代 ${descendants} 篇。`,
      status: 'done',
      metaText: ''
    });
    pushLineageLog({
      title: '结果渲染',
      detail: '血缘树已渲染并自动切换到血缘树视图。',
      status: 'done'
    });

    const graphId = String(graphData.value?.graph_id || '').trim();
    const token = String(accessTokenRef.value || '').trim();
    const historyLogIndex = pushLineageLog({
      title: '研究历史同步',
      detail: graphId && token ? '正在同步本次血缘树到研究历史...' : '当前会话未写入研究历史（不影响当前结果）。',
      status: graphId && token ? 'doing' : 'fallback'
    });
    if (graphId && token) {
      void updateResearchHistoryLineageStatus({
        graph_id: graphId,
        seed_paper_id: seedPaperId,
        ancestor_count: ancestors,
        descendant_count: descendants,
        lineage_payload: payload
      }, token).then((result) => {
        updateLineageLog(historyLogIndex, {
          detail: result?.updated ? '研究历史已更新。' : '未找到可更新的研究历史记录（已跳过）。',
          status: result?.updated ? 'done' : 'fallback'
        });
      }).catch(() => {
        updateLineageLog(historyLogIndex, {
          detail: '研究历史更新失败（已跳过，不影响当前结果）。',
          status: 'fallback'
        });
        // keep lineage generation non-blocking even if history status update fails
      });
    }

    pushLineageLog({
      title: '结果完成',
      detail: `血缘树构建完成，祖先 ${ancestors} 篇，后代 ${descendants} 篇。`,
      status: 'done'
    });
    setStepStatus(4, 'done', `血缘树已生成，关联论文 ${ancestors + descendants} 篇。`);
    setStepAction('lineage', null);
  }

  async function handleStepAction(stepKey) {
    const key = String(stepKey || '').trim().toLowerCase();
    if (key === 'checkpoint') {
      if (unifiedRuntimeActive.value) {
        await continueAfterUnifiedCheckpoint('checkpoint');
        return;
      }
      await continueAfterLegacyCheckpoint();
      return;
    }
    if (key === 'lineage') {
      if (unifiedRuntimeActive.value && waitingResearchCheckpoint.value === 'checkpoint_2') {
        await continueAfterUnifiedCheckpoint('lineage');
        return;
      }
      await generateLineageTree();
    }
  }

  watch(
    canViewLineage,
    (next) => {
      notifyLineageAvailability(Boolean(next));
    },
    { immediate: true }
  );

  onUnmounted(() => {
    void stopUnifiedRuntimeSession({ silent: true });
    resetUnifiedRuntimeState();
  });

  return {
    steps,
    graphLoading,
    graphData,
    errorMessage,
    lineageLoading,
    lineageData,
    lineageErrorMessage,
    graphStats,
    workflowProgress,
    currentTaskText,
    nextTaskText,
    activeStepHint,
    activeViewKey,
    canViewLineage,
    runWorkflow,
    handleStepAction
  };
}
