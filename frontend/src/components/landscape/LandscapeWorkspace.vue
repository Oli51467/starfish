<template>
  <section class="panel landscape-workspace-panel">
    <div class="landscape-workspace-body">
      <div class="landscape-graph-tools">
        <button
          class="btn graph-refresh-btn"
          type="button"
          aria-label="刷新图谱"
          title="刷新图谱"
          :disabled="activeTab !== 'graph' || !hasGraph"
          @click="refreshGraph"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M13.5 8a5.5 5.5 0 1 1-1.16-3.4" />
            <path d="M13.5 3.5v3.1h-3.1" />
          </svg>
        </button>

        <div class="landscape-tab-switcher" role="tablist" aria-label="领域分析视图切换">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="knowledge-switch-btn mono"
            :class="{ 'is-active': activeTab === tab.key }"
            type="button"
            role="tab"
            :aria-selected="activeTab === tab.key"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>

      <template v-if="activeTab === 'graph'">
        <LoadingState v-if="loading && !hasGraph" :message="loadingMessage || '正在生成领域图谱...'" />
        <ErrorBoundary v-else-if="errorMessage && !hasGraph" :message="errorMessage" />
        <KnowledgeGraphCanvas v-else-if="hasGraph" ref="graphCanvasRef" :graph="graphData" />
        <section v-else class="panel workflow-empty">
          <p class="muted">等待图谱数据...</p>
        </section>
      </template>

      <template v-else>
        <LoadingState v-if="loading && !insightText" :message="loadingMessage || '正在生成深度总结...'" />
        <ErrorBoundary v-else-if="errorMessage && !insightText" :message="errorMessage" />
        <article v-else class="landscape-insight-article">
          <p class="landscape-insight-text">{{ insightText || '暂无趋势洞察。' }}</p>
        </article>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';

import ErrorBoundary from '../common/ErrorBoundary.vue';
import LoadingState from '../common/LoadingState.vue';
import KnowledgeGraphCanvas from '../graph/KnowledgeGraphCanvas.vue';

const props = defineProps({
  graphData: {
    type: Object,
    default: null
  },
  insightText: {
    type: String,
    default: ''
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
  }
});

const tabs = [
  { key: 'graph', label: '知识图谱' },
  { key: 'insight', label: '趋势洞察' }
];

const activeTab = ref('graph');
const graphCanvasRef = ref(null);
const hasGraph = computed(() => Array.isArray(props.graphData?.nodes) && props.graphData.nodes.length > 0);

async function refreshGraph() {
  await graphCanvasRef.value?.refreshGraphDisplay?.();
}
</script>

<style scoped>
.landscape-workspace-panel {
  height: 100%;
  min-height: 0;
  display: grid;
  overflow: hidden;
}

.landscape-tab-switcher {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 4px;
  background: #fff;
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
  top: 14px;
  right: 14px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--shadow-soft);
  padding: 5px 7px;
}

.landscape-workspace-body > * {
  min-height: 0;
}

.landscape-insight-article {
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: #fff;
  padding: 14px;
  margin: 10px;
  height: calc(100% - 20px);
  min-height: 0;
  overflow: auto;
}

.landscape-insight-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.85;
  color: #2f2f2f;
  white-space: pre-wrap;
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
    top: 10px;
    right: 10px;
    padding: 4px 6px;
  }

  .landscape-insight-article {
    margin: 10px;
    padding: 12px;
  }

  .landscape-insight-text {
    font-size: 13px;
    line-height: 1.78;
  }
}
</style>
