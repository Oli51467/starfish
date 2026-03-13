<template>
  <section class="panel">
    <div class="panel-head">
      <h2>必读清单智能排序</h2>
      <button class="btn mono" type="button" @click="load" :disabled="readingListLoading || !mapId">刷新</button>
    </div>

    <div class="panel-body" v-if="!mapId">
      <p class="muted">请先在输入页生成地图。</p>
    </div>

    <div class="panel-body" v-else>
      <LoadingState v-if="readingListLoading" message="正在加载必读清单..." />
      <ErrorBoundary :message="readingListErrorMessage" />

      <template v-if="readingList">
        <div class="card-grid">
          <ImportanceCard v-for="layer in readingList.layers" :key="layer.layer" :layer="layer" />
        </div>

        <div class="paper-grid">
          <PaperCard
            v-for="paper in flatPapers"
            :key="paper.paper_id"
            :paper="paper"
          />
        </div>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted } from 'vue';

import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import LoadingState from '../components/common/LoadingState.vue';
import ImportanceCard from '../components/cards/ImportanceCard.vue';
import PaperCard from '../components/cards/PaperCard.vue';
import { useMapStore } from '../stores/mapStore';
import { usePaperStore } from '../stores/paperStore';

const { mapId } = useMapStore();
const {
  readingList,
  readingListLoading,
  readingListErrorMessage,
  loadReadingList
} = usePaperStore();

const flatPapers = computed(() => {
  const layers = readingList.value?.layers || [];
  return layers.flatMap((layer) => layer.papers || []).slice(0, 12);
});

async function load() {
  if (!mapId.value) return;
  await loadReadingList(mapId.value, { maxPapers: 20 });
}

onMounted(load);
</script>
