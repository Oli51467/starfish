<template>
  <section class="workflow-page paper-fixed-page">
    <div class="workflow-layout paper-fixed-layout paper-workflow-layout">
      <PaperWorkflowPanel
        class="paper-workflow-side"
        :steps="steps"
        :progress="workflowProgress"
        @step-action="handleStepAction"
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
const lastCenteredGraphId = ref('');

const {
  steps,
  graphLoading,
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
  handleStepAction
} = usePaperWorkflow({
  seedRef: computed(() => props.seed),
  resultViewRef: computed(() => props.resultView),
  accessTokenRef: accessToken,
  onStepChange: (payload) => emit('step-change', payload),
  onResultViewChange: (nextView) => emit('result-view-change', nextView),
  onLineageAvailabilityChange: (enabled) => emit('lineage-availability-change', enabled)
});

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

async function autoCenterGeneratedGraph() {
  const graphId = resolveGraphId(graphData.value);
  if (!graphId) return;
  if (activeViewKey.value !== 'graph') return;
  if (lastCenteredGraphId.value === graphId) return;

  await nextTick();
  await nextTick();
  if (workflowGraphViewRef.value?.refreshGraphToMinOverview) {
    await workflowGraphViewRef.value.refreshGraphToMinOverview();
  } else {
    await workflowGraphViewRef.value?.refreshGraphDisplay?.();
  }
  lastCenteredGraphId.value = graphId;
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
  () => [resolveGraphId(graphData.value), activeViewKey.value],
  async ([graphId, viewKey]) => {
    if (!graphId || viewKey !== 'graph') return;
    await autoCenterGeneratedGraph();
  }
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
  gap: 10px;
  grid-template-columns: minmax(380px, 430px) minmax(0, 1fr);
}

.paper-workflow-layout::after {
  display: none;
}

.paper-workflow-side,
.paper-result-side {
  min-height: 0;
}

.paper-workflow-side {
  height: 100%;
}

.paper-result-side {
  overflow: hidden;
}

.workflow-result-shell {
  min-height: 0;
  height: 100%;
  max-height: 100%;
  grid-template-rows: minmax(0, 1fr);
  gap: 0;
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
  }

  .paper-result-side {
    overflow: visible;
  }
}
</style>
