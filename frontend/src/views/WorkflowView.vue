<template>
  <section class="workflow-page paper-fixed-page">
    <div class="workflow-layout paper-fixed-layout paper-workflow-layout">
      <PaperWorkflowPanel
        class="paper-workflow-side"
        :steps="steps"
        :negotiation-by-step="negotiationByStep"
        :insight-inline-config="insightInlineConfig"
        :progress="workflowProgress"
        :can-terminate="canTerminateWorkflow"
        :terminating="terminatingWorkflow"
        @step-action="handleStepAction"
        @insight-config-change="handleInsightConfigChange"
        @terminate="handleWorkflowTerminate"
      />

      <article class="paper-result-side workflow-result-shell">
        <div class="workflow-result-stage">
          <ErrorBoundary v-if="errorMessage && !graphData" :message="errorMessage" />
          <template v-else-if="graphData">
            <KnowledgeGraphView
              ref="workflowGraphViewRef"
              :graph-data="graphData"
              mode="panorama_only"
              :show-tools="resultViewTab === 'graph'"
            >
              <template #tools-extra>
                <div v-if="resultViewTab === 'graph'" class="workflow-canvas-controls">
                  <div class="workflow-canvas-tab-switch" role="tablist" aria-label="结果视图切换">
                    <button
                      class="workflow-canvas-tab-btn mono"
                      :class="{ 'is-active': resultViewTab === 'graph' }"
                      type="button"
                      role="tab"
                      :aria-selected="resultViewTab === 'graph'"
                      @click="resultViewTab = 'graph'"
                    >
                      知识图谱
                    </button>
                    <button
                      class="workflow-canvas-tab-btn mono"
                      :class="{ 'is-active': resultViewTab === 'report' }"
                      type="button"
                      role="tab"
                      :aria-selected="resultViewTab === 'report'"
                      @click="resultViewTab = 'report'"
                    >
                      探索报告
                    </button>
                  </div>
                </div>
              </template>
            </KnowledgeGraphView>

            <section
              v-if="resultViewTab === 'report'"
              class="panel workflow-report-panel"
            >
              <div class="workflow-report-body">
                <div class="workflow-report-head">
                  <p class="workflow-report-firstline mono">{{ insightFirstLine }}</p>
                  <div class="workflow-report-toolbar">
                    <div class="workflow-canvas-tab-switch" role="tablist" aria-label="结果视图切换">
                      <button
                        class="workflow-canvas-tab-btn mono"
                        :class="{ 'is-active': resultViewTab === 'graph' }"
                        type="button"
                        role="tab"
                        :aria-selected="resultViewTab === 'graph'"
                        @click="resultViewTab = 'graph'"
                      >
                        知识图谱
                      </button>
                      <button
                        class="workflow-canvas-tab-btn mono"
                        :class="{ 'is-active': resultViewTab === 'report' }"
                        type="button"
                        role="tab"
                        :aria-selected="resultViewTab === 'report'"
                        @click="resultViewTab = 'report'"
                      >
                        探索报告
                      </button>
                    </div>
                    <div class="workflow-report-download-group">
                      <button
                        class="btn workflow-canvas-icon-btn"
                        type="button"
                        :disabled="!hasInsightReport || insightMarkdownDownloadLoading"
                        aria-label="下载 MD"
                        title="下载 MD"
                        @click="downloadInsightMarkdown"
                      >
                        <svg viewBox="0 0 16 16" aria-hidden="true">
                          <path d="M3.2 2.6h6.1l3.1 3.1v7.7H3.2z" />
                          <path d="M9.3 2.6v3.1h3.1" />
                          <path d="M8 7v4.2" />
                          <path d="M6.3 9.7 8 11.4l1.7-1.7" />
                        </svg>
                      </button>
                      <button
                        class="btn workflow-canvas-icon-btn"
                        type="button"
                        :disabled="!insightReportReady || insightPdfDownloadLoading"
                        aria-label="下载 PDF"
                        title="下载 PDF"
                        @click="downloadInsightPdf"
                      >
                        <svg viewBox="0 0 16 16" aria-hidden="true">
                          <path d="M3.2 2.6h6.1l3.1 3.1v7.7H3.2z" />
                          <path d="M9.3 2.6v3.1h3.1" />
                          <path d="M8 7v4.2" />
                          <path d="M6.3 9.7 8 11.4l1.7-1.7" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
                <div
                  v-if="showInsightStreamingBanner"
                  class="workflow-report-streaming-banner"
                  role="status"
                  aria-live="polite"
                >
                  <span class="workflow-report-streaming-dot" aria-hidden="true"></span>
                  <span class="workflow-report-streaming-text">报告正在深度扩写，请稍候…</span>
                  <span class="workflow-report-streaming-track" aria-hidden="true"></span>
                </div>
                <div v-if="hasInsightReport" class="workflow-report-markdown-block">
                  <pre v-if="insightRestContent" class="workflow-report-markdown">{{ insightRestContent }}</pre>
                </div>
                <div
                  v-else
                  class="workflow-report-waiting"
                  role="status"
                  aria-live="polite"
                >
                  <div class="workflow-report-waiting-orb" aria-hidden="true">
                    <span class="workflow-report-waiting-ring ring-a"></span>
                    <span class="workflow-report-waiting-ring ring-b"></span>
                    <span class="workflow-report-waiting-core"></span>
                  </div>
                  <p class="workflow-report-waiting-title mono">{{ insightWaitingHeadline }}</p>
                  <p class="workflow-report-placeholder muted">
                    {{ insightReportPlaceholderText }}
                  </p>
                  <div class="workflow-report-waiting-stages">
                    <span
                      v-for="item in insightWaitingStages"
                      :key="item.label"
                      class="workflow-report-waiting-stage mono"
                      :class="`is-${item.status}`"
                    >
                      {{ item.label }}
                    </span>
                  </div>
                </div>
              </div>
            </section>
          </template>
          <LoadingState v-else-if="graphLoading" :message="activeStepHint" />
          <section v-else class="panel workflow-empty">
            <p class="muted">等待工作流执行...</p>
          </section>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue';

import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import LoadingState from '../components/common/LoadingState.vue';
import KnowledgeGraphView from '../components/graph/KnowledgeGraphView.vue';
import PaperWorkflowPanel from '../components/workflow/PaperWorkflowPanel.vue';
import { usePaperWorkflow } from '../composables/usePaperWorkflow';
import { useAuthStore } from '../stores/authStore';

const props = defineProps({
  seed: {
    type: Object,
    required: true
  }
});

const emit = defineEmits(['step-change', 'back']);
const { accessToken } = useAuthStore();
const workflowGraphViewRef = ref(null);
const lastCenteredGraphKey = ref('');
const resultViewTab = ref('graph');

const {
  steps,
  negotiationByStep,
  insightInlineConfig,
  graphLoading,
  canTerminateWorkflow,
  terminatingWorkflow,
  graphData,
  insightReportMarkdown,
  insightReportReady,
  insightReportStreaming,
  hasInsightReport,
  insightMarkdownDownloadLoading,
  insightPdfDownloadLoading,
  errorMessage,
  workflowProgress,
  activeStepHint,
  insightReportPlaceholderText,
  runWorkflow,
  terminateWorkflow,
  handleStepAction,
  updateInsightInlineConfig,
  downloadInsightMarkdown,
  downloadInsightPdf
} = usePaperWorkflow({
  seedRef: computed(() => props.seed),
  accessTokenRef: accessToken,
  onStepChange: (payload) => emit('step-change', payload)
});

const insightFirstLine = computed(() => {
  const text = String(insightReportMarkdown.value || '');
  if (!text) return '';
  const firstBreak = text.indexOf('\n');
  if (firstBreak < 0) return text;
  return text.slice(0, firstBreak);
});

const insightRestContent = computed(() => {
  const text = String(insightReportMarkdown.value || '');
  if (!text) return '';
  const firstBreak = text.indexOf('\n');
  if (firstBreak < 0) return '';
  return text.slice(firstBreak + 1);
});

const insightStep = computed(() => steps.value.find((item) => String(item?.key || '').trim() === 'insight') || null);
const insightStepStatus = computed(() => String(insightStep.value?.status || '').trim().toLowerCase());
const showInsightStreamingBanner = computed(() => Boolean(insightReportStreaming.value && hasInsightReport.value));

const insightWaitingHeadline = computed(() => {
  if (insightReportStreaming.value) return '正在生成探索报告正文';
  if (insightStepStatus.value === 'action_required') return '等待参数确认后继续生成';
  if (insightStepStatus.value === 'running') return '正在聚合证据并撰写报告';
  return '探索报告准备中';
});

const insightWaitingStages = computed(() => {
  const labels = ['规划分析维度', '聚合关键证据', '撰写深度报告', '校对引用与导出'];
  let currentIndex = 0;
  if (insightReportStreaming.value) {
    currentIndex = 2;
  } else if (insightStepStatus.value === 'running' || insightStepStatus.value === 'action_required') {
    currentIndex = 1;
  }
  return labels.map((label, index) => ({
    label,
    status: index < currentIndex ? 'done' : index === currentIndex ? 'active' : 'pending'
  }));
});

async function handleWorkflowTerminate() {
  await terminateWorkflow();
}

function handleInsightConfigChange(payload) {
  const field = String(payload?.field || '').trim();
  const value = String(payload?.value || '').trim();
  if (!field) return;
  updateInsightInlineConfig(field, value);
}

function resolveGraphId(payload) {
  return String(payload?.graph_id || '').trim();
}

function resolveGraphCenterKey(payload) {
  const graphId = resolveGraphId(payload);
  if (graphId) return `graph:${graphId}`;
  const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
  const edges = Array.isArray(payload?.edges) ? payload.edges : [];
  if (!nodes.length) return '';
  const query = String(payload?.query || '').trim().toLowerCase();
  return `preview:${query}:n${nodes.length}:e${edges.length}`;
}

async function autoCenterGeneratedGraph() {
  const graphCenterKey = resolveGraphCenterKey(graphData.value);
  if (!graphCenterKey) return;
  if (lastCenteredGraphKey.value === graphCenterKey) return;

  await nextTick();
  await nextTick();
  const graphView = workflowGraphViewRef.value;
  if (!graphView) return;
  if (graphView.refreshGraphToMinOverview) {
    await graphView.refreshGraphToMinOverview();
  } else {
    await graphView.refreshGraphDisplay?.();
  }
  lastCenteredGraphKey.value = graphCenterKey;
}

onMounted(async () => {
  await runWorkflow();
});

watch(
  () => resolveGraphCenterKey(graphData.value),
  async (graphCenterKey) => {
    if (!graphCenterKey) return;
    await autoCenterGeneratedGraph();
  }
);

watch(
  () => props.seed,
  () => {
    lastCenteredGraphKey.value = '';
    resultViewTab.value = 'graph';
  },
  { deep: true }
);
</script>

<style scoped>
.paper-fixed-page {
  height: calc(100dvh - 110px);
  min-height: calc(100vh - 110px);
}

.paper-fixed-layout {
  height: 100%;
  min-height: 0;
  gap: 0;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.paper-workflow-layout::after {
  display: block;
  left: 50%;
  background: var(--line-2);
}

.paper-workflow-layout.is-graph-fullscreen .paper-workflow-side {
  display: none;
}

.paper-workflow-layout.is-graph-fullscreen .paper-result-side {
  padding-left: 0;
  grid-column: 1 / -1;
}

.paper-workflow-side,
.paper-result-side {
  min-height: 0;
}

.paper-workflow-side {
  height: 100%;
  padding-right: 12px;
}

.paper-result-side {
  overflow: hidden;
  padding-left: 12px;
}

.workflow-result-shell {
  display: grid;
  min-height: 0;
  height: 100%;
  max-height: 100%;
  grid-template-rows: minmax(0, 1fr);
}

.workflow-result-stage {
  position: relative;
  min-height: 0;
  height: 100%;
  align-self: stretch;
}

.workflow-result-stage :deep(.knowledge-graph-panel) {
  min-height: 0;
  height: 100%;
  max-height: 100%;
  padding: 2px 0 0;
}

.workflow-result-stage :deep(.knowledge-graph-body-full),
.workflow-result-stage :deep(.knowledge-graph-canvas) {
  min-height: 0;
  height: 100%;
}

.workflow-canvas-controls {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.workflow-canvas-tab-switch {
  display: inline-flex;
  border: 1px solid var(--line-2);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--bg);
}

.workflow-canvas-tab-btn {
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-right: 1px solid var(--line-2);
  background: var(--bg);
  color: var(--text);
  padding: 0 10px;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease;
}

.workflow-canvas-tab-btn:last-child {
  border-right: 0;
}

.workflow-canvas-tab-btn:hover {
  background: var(--panel);
}

.workflow-canvas-tab-btn.is-active {
  background: var(--text);
  color: var(--bg);
}

.workflow-canvas-icon-btn {
  width: 30px;
  height: 30px;
  padding: 0;
  border-radius: var(--radius-sm);
}

.workflow-canvas-icon-btn svg {
  width: 14px;
  height: 14px;
  stroke: currentColor;
  fill: none;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.workflow-report-panel {
  position: absolute;
  top: 2px;
  right: 0;
  bottom: 10px;
  left: 0;
  min-height: 0;
  z-index: 6;
  overflow: hidden;
  box-sizing: border-box;
  border: 1px solid var(--line);
  background: var(--panel);
}

.workflow-report-download-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.workflow-report-body {
  width: 100%;
  height: 100%;
  overflow: auto;
  min-height: 0;
  padding: 12px;
  background:
    radial-gradient(circle at 1px 1px, var(--line) 1px, transparent 1px) 0 0 / 14px 14px,
    var(--bg);
}

.workflow-report-markdown-block {
  min-width: 0;
}

.workflow-report-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 8px;
  margin: 0 0 8px;
}

.workflow-report-toolbar {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.workflow-report-firstline {
  margin: 0;
  min-width: 0;
  white-space: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  max-width: 100%;
  font-size: 12px;
  line-height: 30px;
  color: var(--text);
}

.workflow-report-markdown {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text);
}

.workflow-report-streaming-banner {
  position: relative;
  display: grid;
  grid-template-columns: auto auto 1fr;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, color-mix(in srgb, var(--panel) 85%, var(--bg) 15%), var(--bg));
  margin: 0 0 10px;
  overflow: hidden;
}

.workflow-report-streaming-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text);
  animation: workflow-report-pulse 1.2s ease-in-out infinite;
}

.workflow-report-streaming-text {
  font-size: 12px;
  color: var(--text-soft);
}

.workflow-report-streaming-track {
  position: relative;
  height: 2px;
  width: 100%;
  background: var(--line);
  overflow: hidden;
}

.workflow-report-streaming-track::after {
  content: '';
  position: absolute;
  top: 0;
  left: -25%;
  width: 25%;
  height: 100%;
  background: var(--text);
  animation: workflow-report-scan 1.8s linear infinite;
}

.workflow-report-waiting {
  min-height: 220px;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 10px;
  padding: 14px 10px 4px;
}

.workflow-report-waiting-orb {
  position: relative;
  width: 68px;
  height: 68px;
}

.workflow-report-waiting-ring {
  position: absolute;
  border-radius: 50%;
  inset: 0;
  border: 1px solid var(--line);
}

.workflow-report-waiting-ring.ring-a {
  animation: workflow-report-rotate 6s linear infinite;
}

.workflow-report-waiting-ring.ring-b {
  inset: 8px;
  border-style: dashed;
  animation: workflow-report-rotate-reverse 5s linear infinite;
}

.workflow-report-waiting-core {
  position: absolute;
  inset: 22px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--panel) 70%, var(--text) 30%);
  animation: workflow-report-pulse 1.4s ease-in-out infinite;
}

.workflow-report-waiting-title {
  margin: 0;
  font-size: 12px;
  color: var(--text);
}

.workflow-report-waiting-stages {
  width: min(560px, 100%);
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.workflow-report-waiting-stage {
  font-size: 11px;
  line-height: 1.2;
  padding: 7px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line);
  color: var(--text-soft);
  background: var(--panel);
}

.workflow-report-waiting-stage.is-active {
  color: var(--text);
  border-color: var(--text);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--text) 25%, transparent);
}

.workflow-report-waiting-stage.is-done {
  color: var(--text);
  border-color: var(--line-2);
  background: color-mix(in srgb, var(--bg) 85%, var(--panel) 15%);
}

.workflow-report-placeholder {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  text-align: center;
  max-width: 72ch;
}

@keyframes workflow-report-pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 0.9;
  }

  50% {
    transform: scale(1.14);
    opacity: 0.45;
  }
}

@keyframes workflow-report-scan {
  0% {
    left: -28%;
  }

  100% {
    left: 104%;
  }
}

@keyframes workflow-report-rotate {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

@keyframes workflow-report-rotate-reverse {
  from {
    transform: rotate(360deg);
  }

  to {
    transform: rotate(0deg);
  }
}

@media (max-width: 768px) {
  .paper-fixed-page {
    min-height: calc(100dvh - 86px);
  }
}

@media (max-width: 980px) {
  .paper-fixed-page {
    height: auto;
    min-height: calc(100dvh - 110px);
  }

  .paper-fixed-layout {
    height: auto;
    grid-template-columns: minmax(0, 1fr);
  }

  .paper-workflow-side,
  .paper-result-side {
    height: auto;
    padding-left: 0;
    padding-right: 0;
  }

  .paper-result-side {
    overflow: visible;
  }

  .workflow-report-panel {
    top: 2px;
    right: 0;
    bottom: 8px;
    left: 0;
  }

  .paper-workflow-layout::after {
    display: none;
  }
}

@media (max-width: 768px) {
  .workflow-canvas-tab-btn {
    padding: 0 8px;
    font-size: 11px;
  }

  .workflow-report-body {
    padding: 10px;
  }

  .workflow-report-waiting-stages {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
