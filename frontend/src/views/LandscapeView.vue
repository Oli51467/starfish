<template>
  <section class="workflow-page landscape-fixed-page">
    <div class="workflow-layout landscape-fixed-layout" :class="{ 'is-graph-fullscreen': isGraphFullscreen }">
      <PaperWorkflowPanel
        class="landscape-workflow-side"
        :steps="steps"
        :progress="workflowProgress"
      />

      <article class="landscape-result-side">
        <LandscapeWorkspace
          ref="workspaceRef"
          :graph-data="graphData"
          :loading="loading"
          :loading-message="activeStepHint"
          :error-message="errorMessage"
          :is-graph-fullscreen="isGraphFullscreen"
          @toggle-graph-fullscreen="toggleGraphFullscreen"
        />
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue';

import { generateLandscape } from '../api';
import LandscapeWorkspace from '../components/landscape/LandscapeWorkspace.vue';
import PaperWorkflowPanel from '../components/workflow/PaperWorkflowPanel.vue';
import { buildLandscapeGraphFallback } from '../components/landscape/landscapeGraphAdapter';
import { useAuthStore } from '../stores/authStore';

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
const { accessToken } = useAuthStore();

const STEP_DEFINITION = {
  research: {
    key: 'research',
    title: '领域调研',
    description: '梳理领域主线并识别关键子方向。'
  },
  retrieve: {
    key: 'retrieve',
    title: '论文检索',
    description: '补充各子方向的代表论文并完成筛选。'
  },
  graph: {
    key: 'graph',
    title: '图谱生成',
    description: '生成可交互知识图谱并完成结果整理。'
  }
};

const steps = ref(buildSteps());

const loading = ref(false);
const errorMessage = ref('');
const loadingMessage = ref('正在准备任务...');
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
const workflowProgress = computed(() => {
  const total = Math.max(1, steps.value.length);
  const doneCount = steps.value.filter((item) => String(item.status || '').toLowerCase() === 'done').length;
  const hasRunning = steps.value.some((item) => String(item.status || '').toLowerCase() === 'running');
  const partial = hasRunning ? 0.5 : 0;
  const percent = Math.round(((doneCount + partial) / total) * 100);
  return Math.max(0, Math.min(100, percent));
});
const beijingTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour12: false,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit'
});

function buildSteps() {
  const order = ['research', 'retrieve', 'graph'];
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

function rebuildSteps() {
  const previousMap = new Map(steps.value.map((item) => [item.key, item]));
  steps.value = buildSteps().map((item) => {
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
  const normalizedKey = String(stepKey || '').trim();
  if (normalizedKey === 'summarize') {
    const graphIndex = steps.value.findIndex((item) => item.key === 'graph');
    return graphIndex >= 0 ? graphIndex + 1 : 1;
  }
  const matchedIndex = steps.value.findIndex((item) => item.key === normalizedKey);
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

function formatLandscapeLogTitle(stepKey, rawTimestamp) {
  const key = String(stepKey || '').trim().toLowerCase();
  const timeText = formatBeijingTime(rawTimestamp);
  if (key === 'research') return `Planner Agent ${timeText}`;
  if (key === 'retrieve') return `Retriever Agents ${timeText}`;
  if (key === 'graph') return `Graph Builder Agent ${timeText}`;
  return `Coordinator Agent ${timeText}`;
}

function normalizeLandscapeMessage(stepKey, rawMessage, { running = false } = {}) {
  const key = String(stepKey || '').trim().toLowerCase();
  const message = String(rawMessage || '').trim();
  const messageLower = message.toLowerCase();

  if (key === 'research') {
    if (messageLower.includes('缓存')) {
      return running ? '正在复用历史分析结果并校验一致性...' : '已复用历史分析结果并完成一致性校验。';
    }
    if (messageLower.includes('完成') || messageLower.includes('骨架')) {
      return '领域主线与子方向已整理完成。';
    }
    return running ? '正在梳理领域主线与子方向...' : '已完成领域主线梳理。';
  }

  if (key === 'retrieve') {
    if (messageLower.includes('回放') || messageLower.includes('复用') || messageLower.includes('缓存')) {
      return running ? '正在复用历史检索结果...' : '已复用历史检索结果。';
    }
    if (messageLower.includes('完成') || messageLower.includes('排序')) {
      return '子方向论文收集完成，已整理优先级。';
    }
    return running ? '正在补充各子方向的代表论文...' : '已完成论文补充。';
  }

  if (key === 'summarize') {
    if (messageLower.includes('完成')) {
      return '中间阶段处理完成。';
    }
    return running ? '正在处理中间阶段内容...' : '中间阶段处理完成。';
  }

  if (key === 'graph') {
    if (messageLower.includes('任务完成')) {
      return '研究流程已完成。';
    }
    if (
      messageLower.includes('写入完成')
      || messageLower.includes('保存完成')
      || messageLower.includes('结果已保存')
      || messageLower.includes('跳过图数据库重复写入')
    ) {
      return '图谱结果已保存。';
    }
    if (messageLower.includes('写入') || messageLower.includes('保存')) {
      return running ? '正在保存图谱结果...' : '图谱结果已保存。';
    }
    if (messageLower.includes('校验')) {
      return running ? '正在校验图谱结构...' : '图谱结构校验完成。';
    }
    if (messageLower.includes('构建') || messageLower.includes('刷新知识图谱')) {
      return running ? '正在构建可交互知识图谱...' : '知识图谱已生成。';
    }
    if (messageLower.includes('完成')) {
      return '知识图谱已生成。';
    }
    return running ? '正在构建可交互知识图谱...' : '知识图谱已构建完成。';
  }

  return message || (running ? '处理中...' : '已完成。');
}

function normalizeStepLogs(taskLogs) {
  const grouped = {
    research: [],
    retrieve: [],
    graph: []
  };
  if (!Array.isArray(taskLogs)) return grouped;

  for (const item of taskLogs) {
    const key = String(item?.step_key || '').trim();
    if (!Object.prototype.hasOwnProperty.call(grouped, key)) continue;
    const nextLog = {
      title: formatLandscapeLogTitle(key, item?.timestamp),
      detail: normalizeLandscapeMessage(key, item?.message, { running: toLogStatus(item?.level) === 'doing' }),
      status: toLogStatus(item?.level),
      statusText: toLogStatusText(item?.level),
      metaText: ''
    };
    const bucket = grouped[key];
    const last = bucket[bucket.length - 1];
    if (last && last.detail === nextLog.detail && last.status === nextLog.status) continue;
    bucket.push(nextLog);
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
  const status = String(task?.status || '').trim();
  const stepKey = String(task?.step_key || '').trim() || 'research';
  const currentIndex = stepIndexFromKey(stepKey);

  const message = String(task?.message || '').trim();
  const userMessage = normalizeLandscapeMessage(stepKey, message, { running: status !== 'completed' && status !== 'failed' });
  if (message) {
    loadingMessage.value = userMessage;
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
      step.message = step.index === currentIndex ? userMessage || '步骤失败' : step.message;
      continue;
    }

    if (step.index < currentIndex) {
      step.status = 'done';
      step.message = step.logs.at(-1)?.detail || '已完成';
      continue;
    }
    if (step.index === currentIndex) {
      step.status = 'running';
      step.message = userMessage || step.message;
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
  rebuildSteps();
  resetSteps();
  loading.value = true;
  errorMessage.value = '';
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
        accessToken: accessToken.value,
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
  gap: 10px;
  grid-template-columns: minmax(380px, 430px) minmax(0, 1fr);
}

.landscape-fixed-layout::after {
  display: none;
}

.landscape-workflow-side,
.landscape-result-side {
  min-height: 0;
}

.landscape-workflow-side {
  height: 100%;
}

.landscape-result-side {
  overflow: hidden;
}

.landscape-fixed-layout.is-graph-fullscreen {
  grid-template-columns: minmax(0, 1fr);
}

.landscape-fixed-layout.is-graph-fullscreen::after {
  display: none;
}

.landscape-fixed-layout.is-graph-fullscreen .landscape-workflow-side {
  display: none;
}

@media (max-width: 980px) {
  .landscape-fixed-page {
    height: auto;
    min-height: calc(100dvh - 110px);
  }

  .landscape-fixed-layout {
    height: auto;
    grid-template-columns: minmax(0, 1fr);
  }

  .landscape-workflow-side,
  .landscape-result-side {
    height: auto;
  }

  .landscape-result-side {
    overflow: visible;
  }
}

@media (max-width: 768px) {
  .landscape-fixed-page {
    min-height: calc(100dvh - 86px);
  }
}
</style>
