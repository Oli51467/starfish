<template>
  <section class="panel">
    <div class="panel-head">
      <h2>血缘树</h2>
      <span class="mono muted">Step 4</span>
    </div>

    <div class="panel-body lineage-form-row">
      <input
        class="text-input mono"
        v-model="paperId"
        placeholder="输入 paper_id，例如 paper-1a"
      />
      <button class="btn mono" type="button" @click="load" :disabled="lineageLoading">查询</button>
    </div>

    <div class="panel-body">
      <LoadingState v-if="lineageLoading" message="正在生成血缘树..." />
      <ErrorBoundary :message="lineageErrorMessage" />
      <LineageTree :lineage="lineage" />
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue';

import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import LoadingState from '../components/common/LoadingState.vue';
import LineageTree from '../components/graph/LineageTree.vue';
import { usePaperStore } from '../stores/paperStore';

const {
  lineage,
  lineageLoading,
  lineageErrorMessage,
  loadLineage
} = usePaperStore();
const paperId = ref('paper-1a');

async function load() {
  if (!paperId.value.trim()) return;
  await loadLineage(paperId.value.trim(), {
    ancestorDepth: 2,
    descendantDepth: 2
  });
}
</script>
