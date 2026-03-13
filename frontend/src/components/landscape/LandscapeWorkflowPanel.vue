<template>
  <aside class="workflow-right">
    <div class="workflow-step-list">
      <article
        v-for="step in steps"
        :key="step.index"
        class="workflow-step-item"
        :class="`is-${step.status}`"
      >
        <div class="workflow-step-content">
          <div class="workflow-step-head">
            <p class="workflow-step-index mono">{{ String(step.index).padStart(2, '0') }}</p>
            <p class="workflow-step-title">{{ step.title }}</p>
            <span class="workflow-trace-badge workflow-step-status-badge" :class="`is-${stepBadgeStatus(step.status)}`">
              {{ stepBadgeText(step.status) }}
            </span>
          </div>

          <section v-if="step.logs && step.logs.length" class="workflow-retrieval-trace">
            <article
              v-for="(log, logIndex) in step.logs"
              :key="`${step.key}-log-${logIndex}`"
              class="workflow-trace-item"
            >
              <div class="workflow-trace-head">
                <p class="workflow-trace-title mono">{{ String(logIndex + 1).padStart(2, '0') }} {{ log.title }}</p>
                <span class="workflow-trace-badge" :class="`is-${log.status}`">{{ log.statusText }}</span>
              </div>
              <p class="workflow-trace-detail">{{ log.detail }}</p>
              <p v-if="log.metaText" class="workflow-trace-meta mono">{{ log.metaText }}</p>
            </article>
          </section>

          <section v-if="isGraphStep(step)" class="workflow-step-stats-panel">
            <article
              v-for="item in graphStepStats"
              :key="item.label"
              class="workflow-step-stats-col"
            >
              <p class="workflow-step-stats-value mono">{{ item.value }}</p>
              <p class="workflow-step-stats-label">{{ item.label }}</p>
            </article>
          </section>

          <button v-if="step.status === 'running'" class="workflow-step-active-btn" type="button" disabled>
            正在处理中
          </button>
        </div>
      </article>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  steps: {
    type: Array,
    default: () => []
  },
  graphStats: {
    type: Object,
    default: () => ({
      nodeCount: 0,
      edgeCount: 0,
      directionCount: 0
    })
  }
});

function stepBadgeStatus(stepStatus) {
  const normalized = String(stepStatus || '').toLowerCase();
  if (normalized === 'running') return 'doing';
  if (normalized === 'done') return 'done';
  if (normalized === 'failed') return 'fallback';
  return 'pending';
}

function stepBadgeText(stepStatus) {
  const normalized = String(stepStatus || '').toLowerCase();
  if (normalized === 'running') return 'Doing';
  if (normalized === 'done') return 'Done';
  if (normalized === 'failed') return 'Error';
  return 'Pending';
}

function isGraphStep(step) {
  return String(step?.key || '').trim().toLowerCase() === 'graph';
}

const graphStepStats = computed(() => {
  const nodeCount = Number(props.graphStats?.nodeCount || 0);
  const edgeCount = Number(props.graphStats?.edgeCount || 0);
  const directionCount = Number(props.graphStats?.directionCount || 0);
  return [
    { value: Number.isFinite(nodeCount) ? nodeCount : 0, label: '节点数量' },
    { value: Number.isFinite(edgeCount) ? edgeCount : 0, label: '边数量' },
    { value: Number.isFinite(directionCount) ? directionCount : 0, label: '子方向类型' }
  ];
});
</script>
