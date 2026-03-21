<template>
  <aside class="paper-workflow-panel panel">
    <div class="paper-workflow-progress-row">
      <p class="paper-workflow-progress-title">研究进度</p>
      <div class="paper-workflow-progress-track">
        <div class="paper-workflow-progress-fill" :style="{ width: `${safeProgress}%` }"></div>
      </div>
      <p class="paper-workflow-progress-text mono">{{ safeProgress }}%</p>
    </div>

    <div class="paper-workflow-step-list">
      <article
        v-for="(step, index) in steps"
        :key="step.key || index"
        class="paper-workflow-step-item"
        :class="`is-${stepStatus(step.status)}`"
      >
        <div class="paper-workflow-step-indicator mono">
          <span v-if="stepStatus(step.status) === 'done'">✓</span>
          <span v-else-if="stepStatus(step.status) === 'active'">●</span>
          <span v-else-if="stepStatus(step.status) === 'paused'">⏸</span>
          <span v-else-if="stepStatus(step.status) === 'failed'">!</span>
          <span v-else>○</span>
        </div>
        <div class="paper-workflow-step-main">
          <div class="paper-workflow-step-head">
            <p class="paper-workflow-step-label">{{ step.title || `步骤 ${index + 1}` }}</p>
          </div>

          <div v-if="step.logs && step.logs.length" class="paper-workflow-trace-list">
            <article
              v-for="(log, logIndex) in step.logs"
              :key="`${step.key || index}-log-${logIndex}`"
              class="paper-workflow-trace-item"
            >
              <div class="paper-workflow-trace-head">
                <p class="paper-workflow-trace-title mono">{{ String(logIndex + 1).padStart(2, '0') }} {{ log.title }}</p>
                <span class="paper-workflow-trace-badge mono" :class="`is-${traceStatus(log.status)}`">
                  {{ traceStatusText(log.status) }}
                </span>
              </div>
              <p class="paper-workflow-trace-detail">{{ log.detail }}</p>
            </article>
          </div>

          <button
            v-if="isActionRequired(step)"
            class="btn btn-accent mono paper-workflow-action-btn"
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
  progress: {
    type: Number,
    default: 0
  }
});

defineEmits(['step-action']);

const safeProgress = computed(() => {
  const value = Number(props.progress);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
});

function normalizeStatus(rawStatus) {
  const status = String(rawStatus || '').trim().toLowerCase();
  if (status === 'running' || status === 'doing') return 'active';
  if (status === 'done' || status === 'completed' || status === 'skipped') return 'done';
  if (status === 'failed' || status === 'fallback' || status === 'error') return 'failed';
  if (status === 'action_required') return 'paused';
  return 'pending';
}

function stepStatus(rawStatus) {
  return normalizeStatus(rawStatus);
}

function traceStatus(rawStatus) {
  return normalizeStatus(rawStatus);
}

function traceStatusText(rawStatus) {
  const normalized = normalizeStatus(rawStatus);
  if (normalized === 'active') return '进行中';
  if (normalized === 'done') return '已完成';
  if (normalized === 'failed') return '失败';
  if (normalized === 'paused') return '待确认';
  return '准备中';
}

function isActionRequired(step) {
  return String(step?.status || '').trim().toLowerCase() === 'action_required' && Boolean(step?.action);
}
</script>

<style scoped>
.paper-workflow-panel {
  --workflow-panel-padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--bg);
  padding: var(--workflow-panel-padding);
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  align-content: start;
  gap: 8px;
}

.paper-workflow-progress-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  margin: 2px 0 4px;
  padding: 0;
}

.paper-workflow-progress-title {
  margin: 0;
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
}

.paper-workflow-progress-text {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
}

.paper-workflow-progress-track {
  height: 8px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  overflow: hidden;
}

.paper-workflow-progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.2s ease;
}

.paper-workflow-step-list {
  display: grid;
  align-content: start;
  grid-auto-rows: max-content;
  gap: 9px;
  margin: 0;
  padding-top: 4px;
}

.paper-workflow-step-item {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  padding: 8px 11px;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}

.paper-workflow-step-item.is-active,
.paper-workflow-step-item.is-paused {
  border-color: var(--line-2);
  background: var(--bg);
}

.paper-workflow-step-item.is-failed {
  border-color: var(--accent);
}

.paper-workflow-step-indicator {
  font-size: 12px;
  color: var(--muted);
  line-height: 1;
  min-height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.paper-workflow-step-item.is-active .paper-workflow-step-indicator {
  color: var(--accent);
}

.paper-workflow-step-main {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 6px;
}

.paper-workflow-step-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  min-height: 20px;
  gap: 8px;
}

.paper-workflow-step-label {
  margin: 0;
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-trace-list {
  --step-trace-edge-offset: 22px;
  --step-trace-content-indent: 10px;
  --step-trace-right-gutter: 10px;
  display: grid;
  align-content: start;
  gap: 6px;
  margin-left: calc(var(--step-trace-edge-offset) * -1);
  margin-right: 0;
  min-width: 0;
  max-width: calc(100% + var(--step-trace-edge-offset));
  box-sizing: border-box;
}

.paper-workflow-trace-item {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  padding: 6px 74px 6px var(--step-trace-content-indent);
  display: grid;
  align-content: start;
  gap: 4px;
  position: relative;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}

.paper-workflow-trace-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  align-items: center;
}

.paper-workflow-trace-title {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-trace-badge {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0 6px;
  font-size: 10px;
  line-height: 18px;
  color: var(--muted);
  background: var(--panel);
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
}

.paper-workflow-trace-badge.is-active {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
}

.paper-workflow-trace-badge.is-done {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 40%, var(--line));
}

.paper-workflow-trace-badge.is-failed {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
}

.paper-workflow-trace-detail {
  margin: 0;
  font-size: 11px;
  color: var(--text);
  line-height: 1.45;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-action-btn {
  height: 30px;
  font-size: 11px;
  padding: 0 10px;
  justify-self: center;
}

@media (max-width: 980px) {
  .paper-workflow-panel {
    min-height: auto;
    height: auto;
  }

  .paper-workflow-step-list {
    max-height: none;
  }
}
</style>
