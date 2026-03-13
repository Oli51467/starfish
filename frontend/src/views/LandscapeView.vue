<template>
  <section class="workflow-page landscape-fixed-page">
    <div class="workflow-layout landscape-fixed-layout">
      <article class="workflow-left">
        <LandscapeWorkspace
          :graph-data="graphData"
          :insight-text="insightText"
          :loading="loading"
          :loading-message="activeStepHint"
          :error-message="errorMessage"
        />
      </article>

      <LandscapeWorkflowPanel :steps="steps" />
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';

import { generateLandscape } from '../api';
import LandscapeWorkflowPanel from '../components/landscape/LandscapeWorkflowPanel.vue';
import LandscapeWorkspace from '../components/landscape/LandscapeWorkspace.vue';
import { buildLandscapeGraphFallback } from '../components/landscape/landscapeGraphAdapter';

const props = defineProps({
  query: {
    type: String,
    required: true
  }
});

const emit = defineEmits(['step-change']);

const steps = ref([
  {
    index: 1,
    key: 'research',
    title: '领域调研',
    description: '生成领域骨架并识别核心子方向。',
    status: 'pending',
    message: '',
    logs: []
  },
  {
    index: 2,
    key: 'retrieve',
    title: '论文检索',
    description: 'OpenAlex 优先检索并校验真实论文数据。',
    status: 'pending',
    message: '',
    logs: []
  },
  {
    index: 3,
    key: 'summarize',
    title: '深度总结',
    description: '基于真实数据生成 1000+ 字趋势洞察。',
    status: 'pending',
    message: '',
    logs: []
  },
  {
    index: 4,
    key: 'graph',
    title: '图谱生成',
    description: '实时构建并刷新知识图谱，同时写入图数据库。',
    status: 'pending',
    message: '',
    logs: []
  }
]);

const loading = ref(false);
const errorMessage = ref('');
const loadingMessage = ref('正在准备任务...');
const landscape = ref(null);
const graphData = ref(null);

const activeStep = computed(() => {
  const running = steps.value.find((item) => item.status === 'running');
  if (running) return running;
  const failed = steps.value.find((item) => item.status === 'failed');
  if (failed) return failed;
  const done = [...steps.value].reverse().find((item) => item.status === 'done');
  return done || steps.value[0];
});
const activeStepHint = computed(() => loadingMessage.value || activeStep.value.description || '处理中...');
const insightText = computed(() => String(landscape.value?.trend_summary || '').trim());

function updateStepSignal() {
  emit('step-change', {
    index: activeStep.value.index,
    total: steps.value.length,
    title: activeStep.value.title
  });
}

function resetSteps() {
  for (const step of steps.value) {
    step.status = 'pending';
    step.message = '';
    step.logs = [];
  }
  updateStepSignal();
}

function stepIndexFromKey(stepKey) {
  const indexMap = {
    research: 1,
    retrieve: 2,
    summarize: 3,
    graph: 4
  };
  return indexMap[String(stepKey || '').trim()] || 1;
}

function toLogStatus(level) {
  const normalized = String(level || '').toLowerCase();
  if (normalized === 'done') return 'done';
  if (normalized === 'fallback') return 'fallback';
  if (normalized === 'error') return 'fallback';
  return 'doing';
}

function toLogStatusText(level) {
  const normalized = String(level || '').toLowerCase();
  if (normalized === 'done') return 'Done';
  if (normalized === 'info') return 'Doing';
  if (normalized === 'fallback') return 'Fallback';
  if (normalized === 'error') return 'Error';
  return 'Doing';
}

function normalizeStepLogs(taskLogs) {
  const grouped = {
    research: [],
    retrieve: [],
    summarize: [],
    graph: []
  };
  if (!Array.isArray(taskLogs)) return grouped;

  for (const item of taskLogs) {
    const key = String(item?.step_key || '').trim();
    if (!Object.prototype.hasOwnProperty.call(grouped, key)) continue;
    const meta = item?.meta && typeof item.meta === 'object' ? item.meta : {};
    const metaText = Object.entries(meta)
      .map(([k, v]) => `${k}: ${v}`)
      .slice(0, 4)
      .join(' · ');
    grouped[key].push({
      title: String(item?.timestamp || '').slice(11, 19) || '执行日志',
      detail: String(item?.message || '').trim(),
      status: toLogStatus(item?.level),
      statusText: toLogStatusText(item?.level),
      metaText
    });
  }
  return grouped;
}

function normalizeCompletedLogs(logs) {
  if (!Array.isArray(logs)) return [];
  return logs.map((log) => {
    if (String(log?.status || '').toLowerCase() === 'doing') {
      return {
        ...log,
        status: 'done',
        statusText: 'Done'
      };
    }
    return log;
  });
}

function normalizeLogsByStepStatus(logs, stepStatus) {
  const status = String(stepStatus || '').toLowerCase();
  if (status === 'running') return logs;
  return normalizeCompletedLogs(logs);
}

function applyTaskState(task) {
  const status = String(task?.status || '').trim();
  const stepKey = String(task?.step_key || '').trim() || 'research';
  const currentIndex = stepIndexFromKey(stepKey);

  const message = String(task?.message || '').trim();
  if (message) {
    loadingMessage.value = message;
  }
  if (task?.preview_graph && Array.isArray(task.preview_graph.nodes) && task.preview_graph.nodes.length > 0) {
    graphData.value = task.preview_graph;
  }

  const groupedLogs = normalizeStepLogs(task?.step_logs);
  for (const step of steps.value) {
    step.logs = groupedLogs[step.key] || [];
  }

  for (const step of steps.value) {
    if (status === 'completed') {
      step.status = 'done';
      step.message = step.logs.at(-1)?.detail || '已完成';
      continue;
    }
    if (status === 'failed') {
      if (step.index < currentIndex) {
        step.status = 'done';
      } else if (step.index === currentIndex) {
        step.status = 'failed';
      } else {
        step.status = 'pending';
      }
      step.message = step.index === currentIndex ? message || '步骤失败' : step.message;
      continue;
    }

    if (step.index < currentIndex) {
      step.status = 'done';
      step.message = step.logs.at(-1)?.detail || '已完成';
      continue;
    }
    if (step.index === currentIndex) {
      step.status = 'running';
      step.message = message || step.message;
      continue;
    }
    step.status = 'pending';
    step.message = '';
  }

  for (const step of steps.value) {
    step.logs = normalizeLogsByStepStatus(step.logs, step.status);
  }

  updateStepSignal();
}

function finalizeResult(result) {
  landscape.value = result;
  if (result?.graph_data && Array.isArray(result.graph_data.nodes) && result.graph_data.nodes.length > 0) {
    graphData.value = result.graph_data;
  } else {
    graphData.value = buildLandscapeGraphFallback(result);
  }
}

async function runWorkflow() {
  if (loading.value) return;
  resetSteps();
  loading.value = true;
  errorMessage.value = '';
  landscape.value = null;
  graphData.value = null;
  loadingMessage.value = '正在创建领域全景任务...';

  try {
    const result = await generateLandscape(props.query, (task) => {
      applyTaskState(task);
    });
    finalizeResult(result);
    for (const step of steps.value) {
      step.status = 'done';
      step.logs = normalizeLogsByStepStatus(step.logs, step.status);
      if (!step.message) {
        step.message = step.logs.at(-1)?.detail || '已完成';
      }
    }
    updateStepSignal();
  } catch (error) {
    errorMessage.value = error?.message || '领域全景生成失败。';
    const runningStep = steps.value.find((item) => item.status === 'running') || steps.value[0];
    runningStep.status = 'failed';
    runningStep.message = errorMessage.value;
    updateStepSignal();
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  updateStepSignal();
  await runWorkflow();
});
</script>

<style scoped>
.landscape-fixed-page {
  height: calc(100dvh - 110px);
  min-height: calc(100vh - 110px);
}

.landscape-fixed-layout {
  height: 100%;
  min-height: 0;
}

.landscape-fixed-layout .workflow-left,
.landscape-fixed-layout .workflow-right {
  min-height: 0;
}

.landscape-fixed-layout .workflow-right {
  overflow: auto;
  padding-right: 4px;
}

@media (max-width: 980px) {
  .landscape-fixed-page {
    height: auto;
    min-height: calc(100dvh - 110px);
  }

  .landscape-fixed-layout {
    height: auto;
  }

  .landscape-fixed-layout .workflow-right {
    overflow: visible;
    padding-right: 0;
  }
}

@media (max-width: 768px) {
  .landscape-fixed-page {
    min-height: calc(100dvh - 86px);
  }
}
</style>
