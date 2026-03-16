<template>
  <section class="knowledge-graph-panel" :class="{ 'is-single-view': graphTabs.length <= 1 }">
    <div
      v-if="graphTabs.length > 1"
      class="knowledge-graph-toolbar"
      role="tablist"
      aria-label="知识图谱类型切换"
    >
      <div class="knowledge-graph-switcher">
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

    <KnowledgeGraphCanvas ref="graphCanvasRef" :graph="activeGraph">
      <template #tools-extra>
        <slot name="tools-extra"></slot>
      </template>
    </KnowledgeGraphCanvas>
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
  },
  mode: {
    type: String,
    default: 'multi'
  }
});

const activeGraphKey = ref('full');
const graphCanvasRef = ref(null);

const graphSets = computed(() => buildKnowledgeGraphSets(props.graphData));
const isPanoramaOnlyMode = computed(() => props.mode === 'panorama_only');

const graphTabs = computed(() => {
  if (isPanoramaOnlyMode.value) {
    return [
      {
        key: 'panorama',
        label: '全景图谱'
      }
    ];
  }
  return [
    {
      key: 'full',
      label: '全量图谱'
    },
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
  if (isPanoramaOnlyMode.value) return graphSets.value.panorama;
  if (activeGraphKey.value === 'panorama') return graphSets.value.panorama;
  if (activeGraphKey.value === 'full') return graphSets.value.full;
  if (activeGraphKey.value === 'domain') return graphSets.value.domain;
  return graphSets.value.paper;
});

async function refreshGraphDisplay() {
  if (!graphCanvasRef.value?.refreshGraphDisplay) return;
  await graphCanvasRef.value.refreshGraphDisplay();
}

async function refreshGraphToMinOverview() {
  if (!graphCanvasRef.value?.refreshGraphToMinOverview) return;
  await graphCanvasRef.value.refreshGraphToMinOverview();
}

defineExpose({
  refreshGraphDisplay,
  refreshGraphToMinOverview
});
</script>
