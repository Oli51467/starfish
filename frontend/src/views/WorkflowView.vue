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
          <template v-if="activeViewKey === 'graph'">
            <ErrorBoundary v-if="errorMessage && !graphData" :message="errorMessage" />
            <KnowledgeGraphView
              v-else-if="graphData"
              ref="workflowGraphViewRef"
              :graph-data="graphData"
              mode="panorama_only"
            >
              <template #tools-extra>
                <div class="workflow-result-tabbar" role="tablist" aria-label="论文检索结果切换">
                  <div class="workflow-result-tabs">
                    <button
                      v-for="tab in resultTabs"
                      :key="tab.key"
                      class="workflow-result-tab mono"
                      :class="{ 'is-active': activeViewKey === tab.key }"
                      type="button"
                      role="tab"
                      :aria-selected="activeViewKey === tab.key"
                      :disabled="tab.disabled"
                      @click="activateResultTab(tab)"
                    >
                      {{ tab.label }}
                    </button>
                  </div>
                </div>
              </template>
            </KnowledgeGraphView>
            <LoadingState v-else-if="graphLoading" :message="activeStepHint" />
            <section v-else class="panel workflow-empty">
              <p class="muted">等待工作流执行...</p>
            </section>
          </template>

          <template v-else>
            <LoadingState v-if="lineageLoading && !lineageData" message="正在生成血缘树..." />
            <ErrorBoundary v-else-if="lineageErrorMessage && !lineageData" :message="lineageErrorMessage" />
            <BloodLineageTree
              v-else-if="lineageData"
              ref="workflowLineageViewRef"
              :lineage="lineageData"
              :stretch-timeline="true"
              :focus-paper-id="lineageFocusPaperId"
            >
              <template #tools-extra>
                <div class="workflow-result-tabbar" role="tablist" aria-label="论文检索结果切换">
                  <div class="workflow-result-tabs">
                    <button
                      v-for="tab in resultTabs"
                      :key="`lineage-${tab.key}`"
                      class="workflow-result-tab mono"
                      :class="{ 'is-active': activeViewKey === tab.key }"
                      type="button"
                      role="tab"
                      :aria-selected="activeViewKey === tab.key"
                      :disabled="tab.disabled"
                      @click="activateResultTab(tab)"
                    >
                      {{ tab.label }}
                    </button>
                  </div>
                </div>
              </template>
            </BloodLineageTree>
            <section v-else class="panel workflow-empty">
              <p class="muted">点击左侧第 4 步按钮后生成血缘树。</p>
            </section>
          </template>
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
import BloodLineageTree from '../components/lineage/BloodLineageTree.vue';
import PaperWorkflowPanel from '../components/workflow/PaperWorkflowPanel.vue';
import { usePaperWorkflow } from '../composables/usePaperWorkflow';
import { useAuthStore } from '../stores/authStore';

const props = defineProps({
  seed: {
    type: Object,
    required: true
  },
  resultView: {
    type: String,
    default: 'graph'
  }
});

const emit = defineEmits(['step-change', 'back', 'result-view-change', 'lineage-availability-change']);
const { accessToken } = useAuthStore();
const workflowGraphViewRef = ref(null);
const workflowLineageViewRef = ref(null);
const lastCenteredGraphKey = ref('');

const {
  steps,
  negotiationByStep,
  graphLoading,
  canTerminateWorkflow,
  terminatingWorkflow,
  graphData,
  errorMessage,
  lineageLoading,
  lineageData,
  lineageErrorMessage,
  workflowProgress,
  activeStepHint,
  activeViewKey,
  canViewLineage,
  runWorkflow,
  terminateWorkflow,
  handleStepAction
} = usePaperWorkflow({
  seedRef: computed(() => props.seed),
  resultViewRef: computed(() => props.resultView),
  accessTokenRef: accessToken,
  onStepChange: (payload) => emit('step-change', payload),
  onResultViewChange: (nextView) => emit('result-view-change', nextView),
  onLineageAvailabilityChange: (enabled) => emit('lineage-availability-change', enabled)
});

async function handleWorkflowTerminate() {
  await terminateWorkflow();
}

const resultTabs = computed(() => ([
  {
    key: 'graph',
    label: '知识图谱',
    disabled: false
  },
  {
    key: 'lineage',
    label: '血缘树',
    disabled: !canViewLineage.value
  }
]));

const lineageFocusPaperId = computed(() => {
  const seed = props.seed || {};
  if (!Boolean(seed?.auto_lineage)) return '';
  return String(seed?.lineage_seed_paper_id || seed?.input_value || '').trim();
});

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
  if (activeViewKey.value !== 'graph') return;
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

async function activateResultTab(tab) {
  if (!tab || tab.disabled) return;
  activeViewKey.value = tab.key;
  if (tab.key === 'lineage') {
    await nextTick();
    await nextTick();
    if (workflowLineageViewRef.value?.refreshLineageToMinOverview) {
      await workflowLineageViewRef.value.refreshLineageToMinOverview();
      return;
    }
    await workflowLineageViewRef.value?.refreshLineageDisplay?.();
    return;
  }
  if (tab.key !== 'graph') return;
  await nextTick();
  await nextTick();
  await workflowGraphViewRef.value?.refreshGraphDisplay?.();
}

onMounted(async () => {
  await runWorkflow();
});

watch(
  () => [activeViewKey.value, Boolean(lineageData.value)],
  async ([viewKey, hasLineage]) => {
    if (viewKey !== 'lineage' || !hasLineage) return;
    await nextTick();
    await nextTick();
    if (workflowLineageViewRef.value?.refreshLineageToMinOverview) {
      await workflowLineageViewRef.value.refreshLineageToMinOverview();
      return;
    }
    await workflowLineageViewRef.value?.refreshLineageDisplay?.();
  }
);

watch(
  () => [resolveGraphCenterKey(graphData.value), activeViewKey.value],
  async ([graphCenterKey, viewKey]) => {
    if (!graphCenterKey || viewKey !== 'graph') return;
    await autoCenterGeneratedGraph();
  }
);

watch(
  () => props.seed,
  () => {
    lastCenteredGraphKey.value = '';
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

.paper-workflow-layout.is-graph-fullscreen .paper-workflow-side,
.paper-workflow-layout.is-lineage-fullscreen .paper-workflow-side {
  display: none;
}

.paper-workflow-layout.is-graph-fullscreen .paper-result-side,
.paper-workflow-layout.is-lineage-fullscreen .paper-result-side {
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

.workflow-result-tabbar {
  display: inline-flex;
  align-items: center;
  pointer-events: auto;
}

.workflow-result-tabs {
  width: fit-content;
  border: 1px solid var(--line-2);
  border-radius: var(--radius-md);
  background: var(--bg);
  display: inline-flex;
  align-items: center;
  gap: 0;
  overflow: hidden;
}

.workflow-result-tab {
  height: 30px;
  border: 0;
  border-right: 1px solid var(--line);
  background: var(--bg);
  color: var(--muted);
  font-size: 11px;
  line-height: 1;
  white-space: nowrap;
  padding: 0 10px;
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease;
}

.workflow-result-tab:last-child {
  border-right: 0;
}

.workflow-result-tab:hover:not(:disabled) {
  background: var(--panel);
  color: var(--text);
}

.workflow-result-tab.is-active {
  background: var(--text);
  color: var(--bg);
}

.workflow-result-tab:disabled {
  background: var(--panel);
  color: var(--muted);
  cursor: not-allowed;
}

.workflow-result-stage {
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

.workflow-result-stage :deep(.blood-lineage) {
  min-height: 0;
  height: 100%;
}

@media (max-width: 768px) {
  .paper-fixed-page {
    min-height: calc(100dvh - 86px);
  }

  .workflow-result-tab {
    padding: 0 8px;
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

  .paper-workflow-layout::after {
    display: none;
  }
}
</style>
