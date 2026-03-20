<template>
  <section class="panel landscape-workspace-panel">
    <div class="landscape-workspace-body">
      <div class="landscape-graph-tools">
        <button
          class="btn graph-refresh-btn graph-fullscreen-btn"
          type="button"
          aria-label="切换全屏图谱"
          :title="isGraphFullscreen ? '退出全屏' : '全屏图谱'"
          :disabled="!hasGraph"
          :class="{ 'is-active': isGraphFullscreen }"
          @click="toggleGraphFullscreen"
        >
          <svg v-if="!isGraphFullscreen" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M6 2H2v4M10 2h4v4M14 10v4h-4M2 10v4h4" />
          </svg>
          <svg v-else viewBox="0 0 16 16" aria-hidden="true">
            <path d="M6 6H2V2M10 6h4V2M10 10h4v4M6 10H2v4" />
          </svg>
        </button>

        <button
          class="btn graph-refresh-btn"
          type="button"
          aria-label="刷新图谱"
          title="刷新图谱"
          :disabled="!hasGraph"
          @click="refreshGraph"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M13.5 8a5.5 5.5 0 1 1-1.16-3.4" />
            <path d="M13.5 3.5v3.1h-3.1" />
          </svg>
        </button>
      </div>

      <LoadingState v-if="loading && !hasGraph" :message="loadingMessage || '正在生成领域图谱...'" />
      <ErrorBoundary v-else-if="errorMessage && !hasGraph" :message="errorMessage" />
      <KnowledgeGraphCanvas v-else-if="hasGraph" ref="graphCanvasRef" :graph="graphData" :show-tools="false" />
      <section v-else class="panel workflow-empty">
        <p class="muted">等待图谱数据...</p>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';

import ErrorBoundary from '../common/ErrorBoundary.vue';
import LoadingState from '../common/LoadingState.vue';
import KnowledgeGraphCanvas from '../graph/KnowledgeGraphCanvas.vue';

const props = defineProps({
  graphData: {
    type: Object,
    default: null
  },
  loading: {
    type: Boolean,
    default: false
  },
  loadingMessage: {
    type: String,
    default: ''
  },
  errorMessage: {
    type: String,
    default: ''
  },
  isGraphFullscreen: {
    type: Boolean,
    default: false
  }
});
const emit = defineEmits(['toggle-graph-fullscreen']);

const graphCanvasRef = ref(null);
const hasGraph = computed(() => Array.isArray(props.graphData?.nodes) && props.graphData.nodes.length > 0);
let autoRefreshTimer = 0;

async function refreshGraph() {
  await graphCanvasRef.value?.refreshGraphDisplay?.();
}

function graphSignature(graphData) {
  const nodes = Array.isArray(graphData?.nodes) ? graphData.nodes : [];
  const edges = Array.isArray(graphData?.edges) ? graphData.edges : [];
  const tailNodeId = String(nodes.at(-1)?.id || '');
  const tailEdgeId = String(edges.at(-1)?.id || '');
  return `${nodes.length}:${edges.length}:${tailNodeId}:${tailEdgeId}`;
}

function clearAutoRefreshTimer() {
  if (!autoRefreshTimer) return;
  clearTimeout(autoRefreshTimer);
  autoRefreshTimer = 0;
}

function scheduleAutoRefresh() {
  if (!hasGraph.value) return;
  clearAutoRefreshTimer();
  autoRefreshTimer = window.setTimeout(async () => {
    autoRefreshTimer = 0;
    await nextTick();
    await refreshGraph();
  }, 120);
}

async function refreshGraphAfterTaskCompleted() {
  if (!hasGraph.value) return;
  if (graphCanvasRef.value?.refreshGraphToMinOverview) {
    await graphCanvasRef.value.refreshGraphToMinOverview();
    return;
  }
  await refreshGraph();
}

function toggleGraphFullscreen() {
  emit('toggle-graph-fullscreen');
}

watch(
  () => [props.loading, graphSignature(props.graphData)],
  ([loading, signature], [prevLoading, prevSignature]) => {
    if (!loading) return;
    if (!signature) return;
    if (!prevLoading || signature !== prevSignature) {
      scheduleAutoRefresh();
    }
  }
);

onBeforeUnmount(() => {
  clearAutoRefreshTimer();
});

defineExpose({
  refreshGraph,
  refreshGraphAfterTaskCompleted
});
</script>

<style scoped>
.landscape-workspace-panel {
  height: 100%;
  min-height: 0;
  display: grid;
  overflow: hidden;
}

.landscape-workspace-body {
  position: relative;
  min-height: 0;
  display: grid;
  grid-template-rows: 1fr;
  overflow: hidden;
}

.landscape-graph-tools {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 6px;
}

.landscape-graph-tools .graph-refresh-btn {
  width: 26px;
  height: 26px;
}

.landscape-graph-tools .graph-refresh-btn svg {
  width: 12px;
  height: 12px;
}

.landscape-graph-tools .graph-fullscreen-btn.is-active {
  border-color: var(--line-2);
  background: #f2f6ff;
}

.landscape-graph-tools .graph-fullscreen-btn:hover svg {
  transform: none;
}

.landscape-workspace-body > * {
  min-height: 0;
}

:deep(.knowledge-graph-body),
:deep(.knowledge-graph-body-full) {
  height: 100%;
  min-height: 0;
}

:deep(.knowledge-graph-body-full) {
  padding: 10px;
}

:deep(.knowledge-graph-canvas) {
  height: 100%;
  min-height: 0;
}

@media (max-width: 980px) {
  .landscape-workspace-panel {
    height: auto;
    min-height: 0;
  }
}

@media (max-width: 768px) {
  .landscape-graph-tools {
    top: 8px;
    right: 8px;
  }
}
</style>
