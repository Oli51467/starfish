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
          <KnowledgeGraphView
            v-else-if="graphData"
            ref="workflowGraphViewRef"
            :graph-data="graphData"
            mode="panorama_only"
          />
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

const {
  steps,
  negotiationByStep,
  graphLoading,
  canTerminateWorkflow,
  terminatingWorkflow,
  graphData,
  errorMessage,
  workflowProgress,
  activeStepHint,
  runWorkflow,
  terminateWorkflow,
  handleStepAction
} = usePaperWorkflow({
  seedRef: computed(() => props.seed),
  accessTokenRef: accessToken,
  onStepChange: (payload) => emit('step-change', payload)
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

  .paper-workflow-layout::after {
    display: none;
  }
}
</style>
