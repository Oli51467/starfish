<template>
  <section class="workflow-page">
    <div class="workflow-layout">
      <article class="workflow-left">
        <ErrorBoundary v-if="errorMessage && !graphData" :message="errorMessage" />
        <KnowledgeGraphView v-else-if="graphData" :graph-data="graphData" mode="panorama_only" />
        <LoadingState v-else-if="graphLoading" :message="activeStepHint" />
        <section v-else class="panel workflow-empty">
          <p class="muted">等待工作流执行...</p>
        </section>
      </article>

      <LandscapeWorkflowPanel :steps="steps" :graph-stats="graphStats" />
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';

import { buildKnowledgeGraph, getKnowledgeGraph, retrieveKnowledgePapers } from '../api';
import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import KnowledgeGraphView from '../components/graph/KnowledgeGraphView.vue';
import { buildKnowledgeGraphSets } from '../components/graph/knowledgeGraphModel';
import LandscapeWorkflowPanel from '../components/landscape/LandscapeWorkflowPanel.vue';
import LoadingState from '../components/common/LoadingState.vue';

const props = defineProps({
  seed: {
    type: Object,
    required: true
  }
});

const emit = defineEmits(['step-change', 'back']);

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
  }
]);

const graphLoading = ref(false);
const graphData = ref(null);
const errorMessage = ref('');

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
  emit('step-change', {
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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toStatusText(status) {
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'doing' || normalized === 'running') return '进行中';
  if (normalized === 'done') return '已完成';
  if (normalized === 'pending') return '准备中';
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

function createRetrievalRunningMessage(inputType) {
  if (inputType === 'arxiv_id') return '正在解析 arXiv ID，定位种子论文并扩展引用网络...';
  if (inputType === 'doi') return '正在解析 DOI，定位种子论文并扩展引用网络...';
  return '正在执行网页检索、候选抓取与筛选...';
}

function parsePaperRangeYears(rawValue) {
  const parsed = Number(rawValue);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.min(30, Math.round(parsed));
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

function createRunningBuildLogs() {
  return [];
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

function resetSteps() {
  for (const step of steps.value) {
    step.status = 'pending';
    step.message = '';
    step.logs = [];
  }
  updateStepSignal();
}

async function runWorkflow() {
  if (graphLoading.value) return;
  resetSteps();
  errorMessage.value = '';
  graphLoading.value = true;

  try {
    const inputType = String(props.seed?.input_type || 'domain').trim().toLowerCase();
    setStepStatus(1, 'running', createRetrievalRunningMessage(inputType));
    setStepLogs('retrieve', createRunningRetrievalLogs(inputType));
    const paperRangeYears = parsePaperRangeYears(props.seed?.paper_range_years);
    const retrieval = await retrieveKnowledgePapers({
      query: props.seed.input_value,
      input_type: inputType,
      paper_range_years: paperRangeYears,
      max_papers: 12
    });
    const retrievalQuery = String(retrieval?.query || props.seed.input_value).trim() || props.seed.input_value;
    await playRetrievalTrace(retrieval.steps || []);
    if (!Array.isArray(retrieval.steps) || !retrieval.steps.length) {
      setStepLogs('retrieve', createFallbackRetrievalLogs(retrieval));
    }
    setStepStatus(
      1,
      'done',
      `${retrieval.selected_count} 篇论文已筛选（候选 ${retrieval.candidate_count}）。`
    );
    graphData.value = buildRetrievalPreviewGraph(retrievalQuery, retrieval.papers || []);

    setStepStatus(2, 'running', '正在建图并抽取实体关系...');
    setStepLogs('graph', createRunningBuildLogs());
    const result = await buildKnowledgeGraph({
      query: retrievalQuery,
      max_papers: 12,
      max_entities_per_paper: 6,
      prefetched_papers: retrieval.papers || []
    });
    let resolvedGraph = result;
    let storageHint = '已使用实时结果。';
    if (result.stored_in_neo4j) {
      try {
        resolvedGraph = await getKnowledgeGraph(result.graph_id);
        storageHint = '已写入并从 Neo4j 回读。';
      } catch (neo4jReadError) {
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
  } catch (error) {
    const failed = activeStep.value?.index || 2;
    setStepStatus(failed, 'failed', '步骤执行失败。');
    errorMessage.value = error.message || '工作流执行失败。';
    const failedKey = failed === 1 ? 'retrieve' : 'graph';
    const target = steps.value.find((item) => item.key === failedKey);
    const nextLogs = [...(target?.logs || []), {
      title: '执行异常',
      detail: errorMessage.value,
      status: 'fallback',
      statusText: toStatusText('error'),
      metaText: ''
    }];
    setStepLogs(failedKey, nextLogs);
  } finally {
    graphLoading.value = false;
    updateStepSignal();
  }
}

onMounted(async () => {
  updateStepSignal();
  await runWorkflow();
});
</script>
