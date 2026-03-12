<template>
  <section class="panel map-panel">
    <div class="panel-head">
      <h2>领域地图</h2>
      <span class="mono muted">{{ nodeCount }} nodes / {{ edgeCount }} edges</span>
    </div>

    <div class="map-body" v-if="mapData">
      <div class="map-grid">
        <article v-for="node in mapData.nodes" :key="node.id" class="map-node-card">
          <p class="map-node-title">{{ node.label }}</p>
          <p class="mono muted">论文数 {{ node.paper_count }} · 趋势 {{ node.trend }}</p>
        </article>
      </div>

      <div class="map-summary">
        <p class="result-title mono">趋势解读</p>
        <p>{{ mapData.trend_summary }}</p>
      </div>
    </div>

    <div class="empty-state" v-else>
      <p>请先在输入页提交任务并生成地图。</p>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  mapData: {
    type: Object,
    default: () => null
  }
});

const nodeCount = computed(() => props.mapData?.nodes?.length || 0);
const edgeCount = computed(() => props.mapData?.edges?.length || 0);
</script>
