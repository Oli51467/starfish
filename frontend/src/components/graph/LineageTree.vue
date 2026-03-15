<template>
  <section class="panel lineage-panel">
    <div class="panel-head">
      <h2>血缘树</h2>
      <span class="mono muted">Skeleton</span>
    </div>

    <div class="lineage-body" v-if="lineage">
      <article class="lineage-root">
        <p class="result-title mono">当前论文</p>
        <p>{{ rootPaper.title || '未知论文' }}</p>
      </article>

      <div class="lineage-columns">
        <section>
          <p class="result-title mono">祖先</p>
          <ul class="simple-list">
            <li v-for="item in lineage.ancestors" :key="item.paper_id || item.id">
              {{ item.title }}
            </li>
          </ul>
        </section>

        <section>
          <p class="result-title mono">后代</p>
          <ul class="simple-list">
            <li v-for="item in lineage.descendants" :key="item.paper_id || item.id">
              {{ item.title }}
            </li>
          </ul>
        </section>
      </div>
    </div>

    <div class="empty-state" v-else>
      <p>输入论文 ID 后查看血缘树骨架。</p>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  lineage: {
    type: Object,
    default: () => null
  }
});

const rootPaper = computed(() => props.lineage?.root || props.lineage?.root_paper || {});
</script>
