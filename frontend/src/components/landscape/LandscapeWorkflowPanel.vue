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
              <span v-if="isDoingStatus(stepBadgeStatus(step.status))" class="workflow-badge-spinner" aria-hidden="true"></span>
              {{ stepBadgeText(step.status) }}
            </span>
          </div>
          <p class="workflow-step-desc">{{ step.description }}</p>
          <p v-if="step.message" class="workflow-step-message mono">{{ step.message }}</p>

          <section v-if="step.logs && step.logs.length" class="workflow-retrieval-trace">
            <article
              v-for="(log, logIndex) in step.logs"
              :key="`${step.key}-log-${logIndex}`"
              class="workflow-trace-item"
            >
              <div class="workflow-trace-head">
                <p class="workflow-trace-title mono">{{ String(logIndex + 1).padStart(2, '0') }} {{ log.title }}</p>
                <span class="workflow-trace-badge" :class="`is-${traceBadgeStatus(log.status)}`">
                  <span v-if="isDoingStatus(traceBadgeStatus(log.status))" class="workflow-badge-spinner" aria-hidden="true"></span>
                  {{ traceBadgeText(log.status) }}
                </span>
              </div>
              <p class="workflow-trace-detail">{{ log.detail }}</p>
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
            <span class="workflow-badge-spinner" aria-hidden="true"></span>
            正在处理中
          </button>
          <button
            v-else-if="isActionRequired(step)"
            class="workflow-step-active-btn"
            type="button"
            :disabled="Boolean(step?.action?.disabled)"
            @click="$emit('step-action', step.key)"
          >
            {{ String(step?.action?.label || '继续执行') }}
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
defineEmits(['step-action']);

function normalizeStatusKey(rawStatus) {
  const normalized = String(rawStatus || '').toLowerCase();
  if (normalized === 'action_required') return 'pending';
  if (['running', 'doing', 'info'].includes(normalized)) return 'doing';
  if (['done', 'completed'].includes(normalized)) return 'done';
  if (['failed', 'error', 'fallback'].includes(normalized)) return 'fallback';
  return 'pending';
}

function stepBadgeStatus(stepStatus) {
  return normalizeStatusKey(stepStatus);
}

function stepBadgeText(stepStatus) {
  const raw = String(stepStatus || '').toLowerCase();
  if (raw === 'action_required') return '待操作';
  const status = stepBadgeStatus(stepStatus);
  if (status === 'doing') return '进行中';
  if (status === 'done') return '已完成';
  if (status === 'fallback') return '失败';
  return '准备中';
}

function traceBadgeStatus(logStatus) {
  return normalizeStatusKey(logStatus);
}

function traceBadgeText(logStatus) {
  const status = traceBadgeStatus(logStatus);
  if (status === 'doing') return '进行中';
  if (status === 'done') return '已完成';
  if (status === 'fallback') return '失败';
  return '准备中';
}

function isDoingStatus(status) {
  return String(status || '').toLowerCase() === 'doing';
}

function isActionRequired(step) {
  return String(step?.status || '').toLowerCase() === 'action_required' && Boolean(step?.action);
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
