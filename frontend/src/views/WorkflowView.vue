<template>
  <section class="workflow-page">
    <div class="workflow-layout">
      <article class="workflow-left">
        <LoadingState v-if="graphLoading" :message="activeStepHint" />
        <ErrorBoundary v-else-if="errorMessage" :message="errorMessage" />
        <KnowledgeGraphView v-else-if="graphData" :graph-data="graphData" />
        <section v-else class="panel workflow-empty">
          <p class="muted">等待工作流执行...</p>
        </section>
      </article>

      <aside class="workflow-right">
        <div class="workflow-step-list">
          <article
            v-for="step in steps"
            :key="step.index"
            class="workflow-step-item"
            :class="`is-${step.status}`"
          >
            <p class="workflow-step-index mono">{{ String(step.index).padStart(2, '0') }}</p>
            <div class="workflow-step-content">
              <p class="workflow-step-title">{{ step.title }}</p>
              <p class="workflow-step-desc muted">{{ step.description }}</p>
              <p v-if="step.message" class="workflow-step-message mono">{{ step.message }}</p>
              <section v-if="getTraceByStep(step.index).length" class="workflow-retrieval-trace">
                <article
                  v-for="(trace, traceIndex) in getTraceByStep(step.index)"
                  :key="`trace-${step.index}-${traceIndex}`"
                  class="workflow-trace-item"
                >
                  <div class="workflow-trace-head">
                    <p class="workflow-trace-title mono">{{ String(traceIndex + 1).padStart(2, '0') }} {{ trace.title }}</p>
                    <span class="workflow-trace-badge" :class="`is-${trace.status}`">{{ trace.statusText }}</span>
                  </div>
                  <p class="workflow-trace-detail">{{ trace.detail }}</p>
                  <p v-if="trace.metaText" class="workflow-trace-meta mono">{{ trace.metaText }}</p>
                  <div v-if="trace.links.length" class="workflow-trace-links">
                    <a
                      v-for="(link, linkIndex) in trace.links"
                      :key="`trace-link-${traceIndex}-${linkIndex}`"
                      class="workflow-trace-link mono"
                      :href="link"
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {{ shortenLink(link) }}
                    </a>
                  </div>
                </article>
              </section>
            </div>
          </article>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';

import { buildKnowledgeGraph, getKnowledgeGraph, retrieveKnowledgePapers } from '../api';
import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import KnowledgeGraphView from '../components/graph/KnowledgeGraphView.vue';
import LoadingState from '../components/common/LoadingState.vue';

const props = defineProps({
  seed: {
    type: Object,
    required: true
  }
});

const emit = defineEmits(['step-change', 'back']);

const steps = ref([
  { index: 1, title: '论文检索', description: '检索与当前输入相关的论文集合。', status: 'pending', message: '' },
  { index: 2, title: '知识图谱构建', description: '构建图谱并完成实体关系抽取。', status: 'pending', message: '' }
]);

const graphLoading = ref(false);
const graphData = ref(null);
const errorMessage = ref('');
const retrievalTrace = ref([]);
const buildTrace = ref([]);

const activeStep = computed(() => {
  const running = steps.value.find((item) => item.status === 'running');
  if (running) return running;

  const failed = steps.value.find((item) => item.status === 'failed');
  if (failed) return failed;

  const done = [...steps.value].reverse().find((item) => ['done', 'skipped'].includes(item.status));
  return done || steps.value[0];
});

const activeStepHint = computed(() => activeStep.value?.description || '工作流运行中...');

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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatProviderLabel(provider) {
  const value = String(provider || '').trim().toLowerCase();
  if (value === 'semantic_scholar') return 'Semantic Scholar';
  if (value === 'openalex') return 'OpenAlex';
  if (value === 'mock') return 'Mock';
  return provider || 'Unknown';
}

function shortenLink(link) {
  try {
    const parsed = new URL(String(link || ''));
    return `${parsed.hostname}${parsed.pathname}`;
  } catch {
    return String(link || '');
  }
}

function normalizeTraceStep(step) {
  const links = Array.isArray(step?.links)
    ? step.links.map((item) => String(item || '').trim()).filter(Boolean)
    : [];
  const providerLabel = formatProviderLabel(step?.provider);
  const count = Number(step?.count);
  const elapsedMs = Number(step?.elapsed_ms);
  const status = String(step?.status || '').toLowerCase() === 'fallback' ? 'fallback' : 'done';
  const metaParts = [];
  if (providerLabel) metaParts.push(`来源 ${providerLabel}`);
  if (Number.isFinite(count) && count > 0) metaParts.push(`数量 ${count}`);
  if (Number.isFinite(elapsedMs) && elapsedMs > 0) metaParts.push(`耗时 ${Math.round(elapsedMs)}ms`);
  return {
    title: String(step?.title || ''),
    detail: String(step?.detail || ''),
    status,
    statusText: status === 'fallback' ? 'Fallback' : 'Done',
    links,
    metaText: metaParts.join(' · ')
  };
}

async function playRetrievalTrace(rawSteps) {
  retrievalTrace.value = [];
  const items = Array.isArray(rawSteps) ? rawSteps.map(normalizeTraceStep) : [];
  for (const item of items) {
    retrievalTrace.value = [...retrievalTrace.value, item];
    await sleep(220);
  }
}

function normalizeBuildTraceStep(step) {
  const status = String(step?.status || '').toLowerCase() === 'fallback' ? 'fallback' : 'done';
  const elapsedMs = Number(step?.elapsed_ms);
  const metaParts = [];
  if (Number.isFinite(elapsedMs) && elapsedMs > 0) metaParts.push(`耗时 ${Math.round(elapsedMs)}ms`);
  return {
    title: String(step?.title || ''),
    detail: String(step?.detail || ''),
    status,
    statusText: status === 'fallback' ? 'Fallback' : 'Done',
    links: [],
    metaText: metaParts.join(' · ')
  };
}

function normalizeBuildTrace(rawSteps, result) {
  const fromBackend = Array.isArray(rawSteps)
    ? rawSteps.map(normalizeBuildTraceStep).filter((item) => item.title || item.detail)
    : [];
  if (fromBackend.length >= 2) return fromBackend.slice(0, 2);

  const fallbackItems = [
    normalizeBuildTraceStep({
      title: '建图与实体关系抽取',
      detail: `已构建 ${Number(result?.paper_count || 0)} 个论文节点、${Number(result?.entity_count || 0)} 个实体节点和 ${Number(result?.domain_count || 0)} 个领域节点。`,
      status: 'done',
      elapsed_ms: 0
    }),
    normalizeBuildTraceStep({
      title: '图谱落库与回读准备',
      detail: result?.stored_in_neo4j
        ? `已写入 Neo4j（graph_id=${String(result?.graph_id || '')}），支持回读验证。`
        : 'Neo4j 不可用，已保留实时构建结果。',
      status: result?.stored_in_neo4j ? 'done' : 'fallback',
      elapsed_ms: 0
    })
  ];
  return [...fromBackend, ...fallbackItems].slice(0, 2);
}

function getTraceByStep(stepIndex) {
  if (stepIndex === 1) return retrievalTrace.value;
  if (stepIndex === 2) return buildTrace.value;
  return [];
}

function resetSteps() {
  for (const step of steps.value) {
    step.status = 'pending';
    step.message = '';
  }
  retrievalTrace.value = [];
  buildTrace.value = [];
  updateStepSignal();
}

async function runWorkflow() {
  if (graphLoading.value) return;
  resetSteps();
  errorMessage.value = '';
  graphLoading.value = true;

  try {
    setStepStatus(1, 'running', '正在执行网页检索、候选抓取与筛选...');
    const retrieval = await retrieveKnowledgePapers({
      query: props.seed.input_value,
      max_papers: 12
    });
    await playRetrievalTrace(retrieval.steps || []);
    setStepStatus(
      1,
      'done',
      `${retrieval.selected_count} 篇论文已筛选（候选 ${retrieval.candidate_count}，来源 ${formatProviderLabel(retrieval.provider)}）。`
    );

    setStepStatus(2, 'running', '正在建图并抽取实体关系...');
    const result = await buildKnowledgeGraph({
      query: props.seed.input_value,
      max_papers: 12,
      max_entities_per_paper: 6,
      prefetched_papers: retrieval.papers || []
    });
    buildTrace.value = normalizeBuildTrace(result?.build_steps, result);
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

    graphData.value = resolvedGraph;
    setStepStatus(2, 'done', `${result.paper_count} 篇论文已建图，抽取 ${result.entity_count} 个实体。${storageHint}`);
  } catch (error) {
    const failed = activeStep.value?.index || 2;
    setStepStatus(failed, 'failed', '步骤执行失败。');
    errorMessage.value = error.message || '工作流执行失败。';
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
