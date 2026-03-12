<template>
  <section class="view-grid map-view-grid">
    <GraphControls :depth="mapInput.depth" @update-depth="updateDepth" @refresh-map="refreshMap" />
    <FieldMap :map-data="mapData" />
  </section>
</template>

<script setup>
import FieldMap from '../components/graph/FieldMap.vue';
import GraphControls from '../components/graph/GraphControls.vue';
import { useMapStore } from '../stores/mapStore';

const { mapInput, mapData, mapId, fetchMapById } = useMapStore();

function updateDepth(value) {
  mapInput.value.depth = value;
}

async function refreshMap() {
  if (!mapId.value) return;
  await fetchMapById(mapId.value);
}
</script>
