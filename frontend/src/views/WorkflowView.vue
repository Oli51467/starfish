<template>
  <section class="workflow-page paper-fixed-page">
    <div class="workflow-layout paper-fixed-layout paper-workflow-layout">
      <PaperWorkflowPanel
        class="paper-workflow-side"
        :steps="steps"
        :negotiation-by-step="negotiationByStep"
        :progress="workflowProgress"
        :can-terminate="canTerminateWorkflow"
        :terminating="terminatingWorkflow"
        @step-action="handleStepAction"
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
                <div v-if="hasInsightReport" class="workflow-report-markdown-block">
                  <pre v-if="insightRestContent" class="workflow-report-markdown">{{ insightRestContent }}</pre>
                </div>
                <p v-else class="workflow-report-placeholder muted">
                  {{ insightReportStreaming ? '正在实时生成报告内容...' : '图谱完成并确认参数后，将在此处显示探索报告。' }}
                </p>
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
  runWorkflow,
  terminateWorkflow,
  handleStepAction,
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

async function handleWorkflowTerminate() {
  await terminateWorkflow();
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

.workflow-report-placeholder {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
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
}
</style>
