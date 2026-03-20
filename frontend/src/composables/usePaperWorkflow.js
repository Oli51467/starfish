import { computed, ref, watch } from 'vue';

import {
  buildKnowledgeGraph,
  getKnowledgeGraph,
  retrieveKnowledgePapers,
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
      search_web: { title: '定位目标论文', detail: '已确认目标论文及其上下文。' },
      retrieve: { title: '扩展关联论文', detail: '已补充目标论文的引用与被引关系。' },
      filter: { title: '筛选核心论文', detail: '已筛选高相关论文。' }
    };
  }
  return {
    search_web: { title: '明确研究范围', detail: '已完成检索范围确认。' },
    retrieve: { title: '收集候选论文', detail: '已补充候选论文集合。' },
    filter: { title: '筛选核心论文', detail: '已筛选高相关论文。' }
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
    ? '正在确认检索方向并收集候选论文...'
    : '正在定位目标论文并扩展关联研究...';
  return [
    {
      title: inputType === 'domain' ? '研究方向确认' : '目标论文定位',
      detail: sourceDetail,
      status: 'doing',
      statusText: toStatusText('doing'),
      metaText: ''
    },
    {
      title: '候选论文筛选',
      detail: '等待候选结果返回后继续。',
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
      title: '候选论文收集',
      detail: '候选论文收集已完成。',
      status: 'done',
      statusText: toStatusText('done'),
      metaText: ''
    },
    {
      title: '候选论文筛选',
      detail: `已从 ${candidateCount} 个候选中筛选 ${selectedCount} 篇论文。`,
      status: 'done',
      statusText: toStatusText('done'),
      metaText: ''
    }
  ];
}

function normalizeBuildTraceStep(step) {
  const phase = String(step?.phase || '').trim().toLowerCase();
  const status = String(step?.status || '').toLowerCase() === 'fallback' ? 'fallback' : 'done';
  if (phase === 'store_graph') {
    return {
      title: '整理并保存图谱',
      detail: status === 'fallback' ? '图谱保存阶段出现波动，已保留当前结果。' : '图谱结构已整理完成。',
      status,
      statusText: toStatusText(status),
      metaText: ''
    };
  }
  return {
    title: '抽取主题关系',
    detail: status === 'fallback' ? '关系整理阶段出现波动，已继续后续流程。' : '论文与主题关系已完成整理。',
    status,
    statusText: toStatusText(status),
    metaText: ''
  };
}

function createRunningBuildLogs() {
  return [
    {
      title: '组织论文关系',
      detail: '正在整理论文之间的关联结构...',
      status: 'doing',
      statusText: toStatusText('doing'),
      metaText: ''
    },
    {
      title: '生成图谱视图',
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
      title: '组织论文关系',
      detail: '已完成论文关系整理。',
      status: 'done',
      statusText: toStatusText('done'),
      metaText: ''
    },
    {
      title: '生成图谱视图',
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
      description: '围绕核心论文展开祖先与后代演化脉络。',
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

  const {
    lineage: lineageData,
    lineageLoading,
    lineageErrorMessage,
    loadLineage,
    clearLineage
  } = usePaperStore();

  const canViewLineage = computed(() => Boolean(lineageLoading.value || lineageData.value));

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
    setStepStatus(4, 'action_required', `已找到核心论文：${seedPaper.title || seedPaper.paperId || '未命名论文'}。`);
    setStepLogs('lineage', [
      {
        title: '核心论文确认',
        detail: '已确认本次血缘树的核心论文，可继续生成。',
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
    graphData.value = resolvedGraph;
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

  async function continueAfterCheckpoint() {
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

  async function runWorkflow() {
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
    const shouldAutoGenerateLineage = Boolean(seed?.auto_lineage);

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

      const selectedCount = Number(retrieval?.selected_count || 0);
      setStepStatus(1, 'done', `已筛选 ${selectedCount} 篇核心论文。`);
      graphData.value = buildRetrievalPreviewGraph(retrievalQuery, retrieval.papers || []);

      setStepStatus(2, 'action_required', '请确认当前需求与检索范围，然后继续。');
      setStepLogs('checkpoint', [
        {
          title: '检索结果概览',
          detail: `当前主题“${retrievalQuery}”已筛选 ${selectedCount} 篇核心论文。`,
          status: 'done',
          statusText: toStatusText('done'),
          metaText: ''
        },
        {
          title: '需求确认',
          detail: `请确认研究范围（${formatSearchRangeLabel(inputType, paperRangeYears)}，${quickMode ? '快速模式' : '普通模式'}）。`,
          status: 'doing',
          statusText: toStatusText('doing'),
          metaText: ''
        }
      ]);
      setStepAction('checkpoint', {
        label: '确认需求并继续',
        disabled: false
      });

      checkpointContext.value = {
        retrieval,
        retrievalQuery,
        inputType,
        seedInputValue: String(seed?.input_value || '').trim(),
        paperRangeYears,
        preferredLineageSeedPaperId,
        shouldAutoGenerateLineage
      };
    } catch (error) {
      errorMessage.value = error?.message || '工作流执行失败。';
      setStepStatus(1, 'failed', '论文检索失败。');
      appendFailureLog('retrieve', errorMessage.value);
    } finally {
      graphLoading.value = false;
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
      title: '核心论文确认',
      detail: '已确认核心论文，开始构建血缘脉络。',
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
      await continueAfterCheckpoint();
      return;
    }
    if (key === 'lineage') {
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
