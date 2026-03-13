<template>
  <section class="panel">
    <div class="panel-head">
      <h2>研究空白探测器</h2>
      <button class="btn mono" type="button" @click="load" :disabled="gapsLoading || !mapId">刷新</button>
    </div>

    <div class="panel-body" v-if="!mapId">
      <p class="muted">请先在输入页生成地图。</p>
    </div>

    <div class="panel-body" v-else>
      <LoadingState v-if="gapsLoading" message="正在检测研究空白..." />
      <ErrorBoundary :message="gapsErrorMessage" />

      <template v-if="gaps">
        <p class="muted gap-summary">{{ gaps.summary }}</p>
        <div class="card-grid">
          <GapCard v-for="gap in gaps.gaps" :key="gap.gap_id" :gap="gap" />
        </div>
      </template>
    </div>
  </section>
</template>

<script setup>
import { onMounted } from 'vue';

import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import LoadingState from '../components/common/LoadingState.vue';
import GapCard from '../components/cards/GapCard.vue';
import { useMapStore } from '../stores/mapStore';
import { usePaperStore } from '../stores/paperStore';

const { mapId } = useMapStore();
const { gaps, gapsLoading, gapsErrorMessage, loadGaps } = usePaperStore();

async function load() {
  if (!mapId.value) return;
  await loadGaps(mapId.value, { minScore: 60 });
}

onMounted(load);
</script>
