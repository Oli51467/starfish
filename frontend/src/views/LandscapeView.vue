<template>
  <section class="workflow-page landscape-fixed-page">
    <div class="workflow-layout landscape-fixed-layout" :class="{ 'is-graph-fullscreen': isGraphFullscreen }">
      <article class="workflow-left">
        <LandscapeWorkspace
          ref="workspaceRef"
          :graph-data="graphData"
          :insight-text="insightText"
          :loading="loading"
          :loading-message="activeStepHint"
          :error-message="errorMessage"
          :is-graph-fullscreen="isGraphFullscreen"
          :summary-enabled="summaryEnabled"
          @toggle-graph-fullscreen="toggleGraphFullscreen"
        />
      </article>

      <LandscapeWorkflowPanel :steps="steps" :graph-stats="graphStats" />
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue';

import { generateLandscape } from '../api';
import LandscapeWorkflowPanel from '../components/landscape/LandscapeWorkflowPanel.vue';
import LandscapeWorkspace from '../components/landscape/LandscapeWorkspace.vue';
import { buildLandscapeGraphFallback } from '../components/landscape/landscapeGraphAdapter';

const props = defineProps({
  query: {
    type: String,
    required: true
  },
  paperRangeYears: {
    type: Number,
    default: null
  },
  quickMode: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['step-change']);

const STEP_DEFINITION = {
  research: {
    key: 'research',
    title: '领域调研',
    description: '生成领域骨架并识别核心子方向。'
  },
  retrieve: {
    key: 'retrieve',
    title: '论文检索',
    description: '并行检索并校验真实论文数据。'
  },
  summarize: {
    key: 'summarize',
    title: '深度总结',
    description: '基于真实数据生成 1000+ 字趋势洞察。'
  },
  graph: {
    key: 'graph',
    title: '图谱生成',
    description: '实时构建并刷新知识图谱，同时写入图数据库。'
  }
};

const summaryEnabled = ref(false);
const steps = ref(buildSteps(summaryEnabled.value));

const loading = ref(false);
const errorMessage = ref('');
const loadingMessage = ref('正在准备任务...');
const landscape = ref(null);
const graphData = ref(null);
const isGraphFullscreen = ref(false);
const workspaceRef = ref(null);

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
const graphStats = computed(() => {
  const nodes = Array.isArray(graphData.value?.nodes) ? graphData.value.nodes : [];
  const edges = Array.isArray(graphData.value?.edges) ? graphData.value.edges : [];
  const directionCount = nodes.filter((node) => (node?.kind || node?.type) === 'domain').length;
  return {
    nodeCount: nodes.length,
    edgeCount: edges.length,
    directionCount
  };
});
const beijingTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour12: false,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit'
});

function buildSteps(enableSummary) {
  const order = enableSummary
    ? ['research', 'retrieve', 'summarize', 'graph']
    : ['research', 'retrieve', 'graph'];
  return order.map((key, index) => ({
    index: index + 1,
    key,
    title: STEP_DEFINITION[key].title,
    description: STEP_DEFINITION[key].description,
    status: 'pending',
    message: '',
    logs: []
  }));
}

function rebuildSteps(enableSummary) {
  const previousMap = new Map(steps.value.map((item) => [item.key, item]));
  steps.value = buildSteps(enableSummary).map((item) => {
    const previous = previousMap.get(item.key);
    if (!previous) return item;
    return {
      ...item,
      status: previous.status,
      message: previous.message,
      logs: Array.isArray(previous.logs) ? previous.logs : []
    };
  });
}

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
  const matchedIndex = steps.value.findIndex((item) => item.key === String(stepKey || '').trim());
  return matchedIndex >= 0 ? matchedIndex + 1 : 1;
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
  if (normalized === 'done') return '已完成';
  if (normalized === 'info') return '进行中';
  if (normalized === 'fallback') return '失败';
  if (normalized === 'error') return '失败';
  return '进行中';
}

function formatBeijingTime(rawTimestamp) {
  const source = String(rawTimestamp || '').trim();
  if (!source) return '--:--:--';
  const parsed = new Date(source);
  if (Number.isNaN(parsed.getTime())) {
    const matched = source.match(/(\d{2}:\d{2}:\d{2})/);
    return matched?.[1] || '--:--:--';
  }
  return beijingTimeFormatter.format(parsed);
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
    if (key === 'graph') continue;
    const meta = item?.meta && typeof item.meta === 'object' ? item.meta : {};
    const metaText = Object.entries(meta)
      .filter(([k]) => !['provider', 'provider_used'].includes(String(k).toLowerCase()))
      .map(([k, v]) => `${k}: ${v}`)
      .slice(0, 4)
      .join(' · ');
    grouped[key].push({
      title: formatBeijingTime(item?.timestamp),
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
        statusText: '已完成'
      };
    }
    return log;
  });
}

function normalizeRunningLogs(logs) {
  if (!Array.isArray(logs)) return [];
  let latestDoingIndex = -1;
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    if (String(logs[index]?.status || '').toLowerCase() === 'doing') {
      latestDoingIndex = index;
      break;
    }
  }
  if (latestDoingIndex < 0) return logs;
  return logs.map((log, index) => {
    if (String(log?.status || '').toLowerCase() !== 'doing') return log;
    if (index === latestDoingIndex) return log;
    return {
      ...log,
      status: 'done',
      statusText: '已完成'
    };
  });
}

function normalizeLogsByStepStatus(logs, stepStatus) {
  const status = String(stepStatus || '').toLowerCase();
  if (status === 'running') return normalizeRunningLogs(logs);
  return normalizeCompletedLogs(logs);
}

function applyTaskState(task) {
  if (typeof task?.summary_enabled === 'boolean' && task.summary_enabled !== summaryEnabled.value) {
    summaryEnabled.value = task.summary_enabled;
    rebuildSteps(summaryEnabled.value);
  }

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
  if (typeof result?.summary_enabled === 'boolean' && result.summary_enabled !== summaryEnabled.value) {
    summaryEnabled.value = result.summary_enabled;
    rebuildSteps(summaryEnabled.value);
  }
  landscape.value = result;
  if (result?.graph_data && Array.isArray(result.graph_data.nodes) && result.graph_data.nodes.length > 0) {
    graphData.value = result.graph_data;
  } else {
    graphData.value = buildLandscapeGraphFallback(result);
  }
}

function toggleGraphFullscreen() {
  isGraphFullscreen.value = !isGraphFullscreen.value;
}

function parsePaperRangeYears(rawValue) {
  const parsed = Number(rawValue);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.min(30, Math.round(parsed));
}

async function runWorkflow() {
  if (loading.value) return;
  rebuildSteps(summaryEnabled.value);
  resetSteps();
  loading.value = true;
  errorMessage.value = '';
  landscape.value = null;
  graphData.value = null;
  loadingMessage.value = '正在创建领域全景任务...';

  try {
    const result = await generateLandscape(
      props.query,
      (task) => {
        applyTaskState(task);
      },
      {
        paperRangeYears: parsePaperRangeYears(props.paperRangeYears),
        quickMode: Boolean(props.quickMode),
      }
    );
    finalizeResult(result);
    for (const step of steps.value) {
      step.status = 'done';
      step.logs = normalizeLogsByStepStatus(step.logs, step.status);
      if (!step.message) {
        step.message = step.logs.at(-1)?.detail || '已完成';
      }
    }
    updateStepSignal();
    await nextTick();
    await workspaceRef.value?.refreshGraphAfterTaskCompleted?.();
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

.landscape-fixed-layout.is-graph-fullscreen {
  grid-template-columns: minmax(0, 1fr);
}

.landscape-fixed-layout.is-graph-fullscreen::after {
  display: none;
}

.landscape-fixed-layout.is-graph-fullscreen .workflow-left {
  padding-right: 0;
}

.landscape-fixed-layout.is-graph-fullscreen .workflow-right {
  display: none;
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
