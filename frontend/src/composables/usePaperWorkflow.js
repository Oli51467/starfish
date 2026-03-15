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

function normalizeTraceStep(step) {
  const count = Number(step?.count);
  const elapsedMs = Number(step?.elapsed_ms);
  const status = String(step?.status || '').toLowerCase() === 'fallback' ? 'fallback' : 'done';
  const metaParts = [];
  if (Number.isFinite(count) && count > 0) metaParts.push(`数量 ${count}`);
  if (Number.isFinite(elapsedMs) && elapsedMs > 0) metaParts.push(`耗时 ${Math.round(elapsedMs)}ms`);
  return {
    title: String(step?.title || ''),
    detail: String(step?.detail || ''),
    status,
    statusText: toStatusText(status),
    metaText: metaParts.join(' · ')
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
  return '不适用';
}

function createRetrievalRunningMessage(inputType) {
  if (inputType === 'arxiv_id') return '正在解析 arXiv ID，定位种子论文并扩展引用网络...';
  if (inputType === 'doi') return '正在解析 DOI，定位种子论文并扩展引用网络...';
  return '正在执行网页检索、候选抓取与筛选...';
}

function createRunningRetrievalLogs(inputType) {
  const sourceDetail = inputType === 'domain'
    ? '正在构造检索请求并访问学术数据源...'
    : '正在定位种子论文并拉取引用/被引关系...';
  return [
    {
      title: inputType === 'domain' ? 'LLM 检索规划与网页搜索' : '种子论文定位与请求构造',
      detail: sourceDetail,
      status: 'doing',
      statusText: toStatusText('doing'),
      metaText: ''
    },
    {
      title: '候选论文评分与筛选',
      detail: '等待候选结果返回后执行评分筛选。',
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
      title: 'LLM 检索规划与网页搜索',
      detail: '候选论文收集已完成。',
      status: 'done',
      statusText: toStatusText('done'),
      metaText: ''
    },
    {
      title: '候选论文评分与筛选',
      detail: `已从 ${candidateCount} 个候选中筛选 ${selectedCount} 篇论文。`,
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
      description: '检索与当前输入相关的论文集合。',
      status: 'pending',
      message: '',
      logs: []
    },
    {
      index: 2,
      key: 'graph',
      title: '知识图谱构建',
      description: '构建图谱并完成实体关系抽取。',
      status: 'pending',
      message: '',
      logs: []
    },
    {
      index: 3,
      key: 'lineage',
      title: '生成血缘树',
      description: '定位种子论文并基于引用关系生成祖先与后代脉络。',
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

  const activeStepHint = computed(() => {
    const current = activeStep.value;
    if (!current) return '工作流运行中...';
    if (current.message) return current.message;
    const latestLog = Array.isArray(current.logs) ? current.logs.at(-1) : null;
    if (latestLog?.detail) return latestLog.detail;
    return current.description || '工作流运行中...';
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

  function setLineageStepAction(action) {
    const target = steps.value.find((item) => item.key === 'lineage');
    if (!target) return;
    target.action = action || null;
  }

  async function playRetrievalTrace(rawSteps) {
    const items = Array.isArray(rawSteps) ? rawSteps.map(normalizeTraceStep) : [];
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

  function createRunningBuildLogs() {
    return [];
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

  async function runWorkflow() {
    if (graphLoading.value) return;
    resetSteps();
    resetLineageState();
    errorMessage.value = '';
    graphLoading.value = true;

    try {
      const seed = seedRef.value || {};
      const inputType = String(seed?.input_type || 'domain').trim().toLowerCase();
      const quickMode = Boolean(seed?.quick_mode);
      setStepStatus(1, 'running', createRetrievalRunningMessage(inputType));
      setStepLogs('retrieve', createRunningRetrievalLogs(inputType));

      const paperRangeYears = parsePaperRangeYears(seed?.paper_range_years);
      const retrieval = await retrieveKnowledgePapers({
        query: seed.input_value,
        input_type: inputType,
        quick_mode: quickMode,
        paper_range_years: paperRangeYears,
        max_papers: 12
      });

      const retrievalQuery = String(retrieval?.query || seed.input_value).trim() || seed.input_value;
      await playRetrievalTrace(retrieval.steps || []);
      if (!Array.isArray(retrieval.steps) || !retrieval.steps.length) {
        setStepLogs('retrieve', createFallbackRetrievalLogs(retrieval));
      }
      setStepStatus(1, 'done', `${retrieval.selected_count} 篇论文已筛选（候选 ${retrieval.candidate_count}）。`);
      graphData.value = buildRetrievalPreviewGraph(retrievalQuery, retrieval.papers || []);

      setStepStatus(2, 'running', '正在建图并抽取实体关系...');
      setStepLogs('graph', createRunningBuildLogs());
      const result = await buildKnowledgeGraph({
        query: retrievalQuery,
        max_papers: 12,
        max_entities_per_paper: 6,
        prefetched_papers: retrieval.papers || [],
        research_type: inputType || 'unknown',
        search_input: String(seed?.input_value || '').trim(),
        search_range: formatSearchRangeLabel(inputType, paperRangeYears)
      }, accessTokenRef.value || '');

      let resolvedGraph = result;
      let storageHint = '已使用实时结果。';
      if (result.stored_in_neo4j) {
        try {
          resolvedGraph = await getKnowledgeGraph(result.graph_id);
          storageHint = '已写入并从 Neo4j 回读。';
        } catch {
          storageHint = '已写入 Neo4j，回读失败，已使用实时结果。';
        }
      }

      setStepLogs('graph', []);
      graphData.value = resolvedGraph;
      const panoramaStats = extractPanoramaStats(resolvedGraph || result || {});
      setStepStatus(
        2,
        'done',
        `全景图谱展示 ${panoramaStats.paperCount} 个论文节点、${panoramaStats.edgeCount} 条论文关联边。${storageHint}`
      );

      const seedPaper = resolveLineageSeed({
        seedInputType: inputType,
        seedInputValue: seed.input_value,
        retrieval,
        graphResult: resolvedGraph || result
      });
      lineageSeed.value = seedPaper;
      setStepStatus(3, 'action_required', `已定位种子论文：${seedPaper.title || seedPaper.paperId || '未命名种子论文'}。`);
      setStepLogs('lineage', [
        {
          title: '种子论文锁定',
          detail: `已识别种子论文 ${seedPaper.paperId || 'unknown'}，可进入血缘树生成。`,
          status: 'done',
          statusText: toStatusText('done'),
          metaText: ''
        }
      ]);
      setLineageStepAction({
        label: '生成血缘树',
        disabled: false
      });
    } catch (error) {
      const failed = activeStep.value?.index || 2;
      setStepStatus(failed, 'failed', '步骤执行失败。');
      errorMessage.value = error?.message || '工作流执行失败。';
      const failedKey = failed === 1 ? 'retrieve' : (failed === 2 ? 'graph' : 'lineage');
      const target = steps.value.find((item) => item.key === failedKey);
      const nextLogs = [
        ...(target?.logs || []),
        {
          title: '执行异常',
          detail: errorMessage.value,
          status: 'fallback',
          statusText: toStatusText('error'),
          metaText: ''
        }
      ];
      setStepLogs(failedKey, nextLogs);
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

    setStepStatus(3, 'running', '正在生成血缘树...');
    pushLineageLog({
      title: '种子论文确认',
      detail: `已锁定种子论文 ${seedPaperId}。`,
      status: 'done'
    });
    pushLineageLog({
      title: '请求参数准备',
      detail: '祖先深度 2，后代深度 2，强制刷新缓存。',
      status: 'done'
    });
    const requestLogIndex = pushLineageLog({
      title: '引用网络构建',
      detail: `正在查询 ${seedPaperId} 的祖先与后代关系。`,
      status: 'doing'
    });
    setLineageStepAction({
      label: '生成血缘树',
      disabled: true
    });

    const requestStartedAt = Date.now();
    const payload = await loadLineage(seedPaperId, {
      ancestorDepth: 2,
      descendantDepth: 2,
      forceRefresh: true
    });

    if (!payload) {
      updateLineageLog(requestLogIndex, {
        detail: lineageErrorMessage.value || '生成血缘树失败。',
        status: 'fallback',
        metaText: `耗时 ${Math.max(1, Date.now() - requestStartedAt)}ms`
      });
      pushLineageLog({
        title: '执行中断',
        detail: '本次血缘树生成失败，可重新发起。',
        status: 'fallback'
      });
      setStepStatus(3, 'failed', lineageErrorMessage.value || '生成血缘树失败。');
      setLineageStepAction({
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
      metaText: `耗时 ${Math.max(1, Date.now() - requestStartedAt)}ms`
    });
    pushLineageLog({
      title: '视图渲染',
      detail: '血缘树画布已渲染，已自动切换到血缘树视图。',
      status: 'done'
    });

    const graphId = String(graphData.value?.graph_id || '').trim();
    const token = String(accessTokenRef.value || '').trim();
    const historyLogIndex = pushLineageLog({
      title: '研究历史同步',
      detail: graphId && token ? '正在同步血缘树状态到研究历史...' : '当前会话未绑定可写入的研究历史记录。',
      status: graphId && token ? 'doing' : 'fallback'
    });
    if (graphId && token) {
      void updateResearchHistoryLineageStatus({
        graph_id: graphId,
        seed_paper_id: seedPaperId,
        ancestor_count: ancestors,
        descendant_count: descendants
      }, token).then((result) => {
        updateLineageLog(historyLogIndex, {
          detail: result?.updated ? '研究历史已更新血缘树状态。' : '未找到可更新的研究历史记录（已跳过）。',
          status: result?.updated ? 'done' : 'fallback'
        });
      }).catch(() => {
        updateLineageLog(historyLogIndex, {
          detail: '研究历史状态更新失败（已跳过，不影响当前结果）。',
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
    setStepStatus(3, 'done', `血缘树已生成：祖先 ${ancestors}，后代 ${descendants}。`);
    setLineageStepAction(null);
  }

  async function handleStepAction(stepKey) {
    if (String(stepKey || '').trim().toLowerCase() !== 'lineage') return;
    await generateLineageTree();
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
    activeStepHint,
    activeViewKey,
    canViewLineage,
    runWorkflow,
    handleStepAction
  };
}
