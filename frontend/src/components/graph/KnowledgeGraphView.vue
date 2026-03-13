<template>
  <section class="knowledge-graph-panel">
    <div class="knowledge-graph-toolbar">
      <button class="btn graph-refresh-btn" type="button" aria-label="刷新图谱" title="刷新图谱" @click="refreshActiveGraph">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M13.5 8a5.5 5.5 0 1 1-1.16-3.4" />
          <path d="M13.5 3.5v3.1h-3.1" />
        </svg>
      </button>
      <div class="knowledge-graph-switcher" role="tablist" aria-label="知识图谱类型切换">
        <button
          v-for="tab in graphTabs"
          :key="tab.key"
          class="knowledge-switch-btn mono"
          :class="{ 'is-active': activeGraphKey === tab.key }"
          type="button"
          role="tab"
          :aria-selected="activeGraphKey === tab.key"
          @click="activeGraphKey = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>
    </div>

    <KnowledgeGraphCanvas ref="graphCanvasRef" :graph="activeGraph" />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';

import KnowledgeGraphCanvas from './KnowledgeGraphCanvas.vue';
import { buildKnowledgeGraphSets } from './knowledgeGraphModel';

const props = defineProps({
  graphData: {
    type: Object,
    required: true
  }
});

const activeGraphKey = ref('paper');
const graphCanvasRef = ref(null);

const graphSets = computed(() => buildKnowledgeGraphSets(props.graphData));

const graphTabs = computed(() => {
  return [
    {
      key: 'paper',
      label: '论文图谱'
    },
    {
      key: 'domain',
      label: '领域图谱'
    }
  ];
});

const activeGraph = computed(() => {
  if (activeGraphKey.value === 'domain') return graphSets.value.domain;
  return graphSets.value.paper;
});

async function refreshActiveGraph() {
  await graphCanvasRef.value?.refreshGraphDisplay?.();
}
</script>
