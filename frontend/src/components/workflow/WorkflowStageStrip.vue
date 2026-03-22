<template>
  <section class="workflow-stage-strip" :class="{ 'is-collapsed': isCollapsed }" aria-label="工作流阶段概览">
    <div v-if="!isCollapsed" class="workflow-stage-panel panel">
      <button
        class="workflow-stage-toggle-btn"
        type="button"
        :aria-label="isCollapsed ? '展开流程图' : '折叠流程图'"
        :title="isCollapsed ? '展开流程图' : '折叠流程图'"
        @click="toggleCollapsed"
      >
        <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
          <path
            v-if="!isCollapsed"
            d="M2.5 7.8 6 4.2l3.5 3.6"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            v-else
            d="M2.5 4.2 6 7.8l3.5-3.6"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>

      <div class="workflow-stage-flow" role="list">
        <template v-for="(step, index) in safeSteps" :key="step?.key || `stage-${index}`">
          <article
            class="workflow-stage-node"
            :class="[
              `shape-${resolveShape(step, index)}`,
              `is-${normalizeStatus(step?.status)}`,
              { 'is-current': resolveStepKey(step, index) === currentStepKey }
            ]"
            role="listitem"
          >
            <div class="workflow-stage-node-frame"></div>
            <div class="workflow-stage-node-content">
              <p class="workflow-stage-node-index mono">{{ String(index + 1).padStart(2, '0') }}</p>
              <p class="workflow-stage-node-label">{{ step?.title || `步骤 ${index + 1}` }}</p>
              <p class="workflow-stage-node-status mono">{{ statusText(step?.status) }}</p>
            </div>
          </article>

          <span
            v-if="index < safeSteps.length - 1"
            class="workflow-stage-connector"
            :class="{ 'is-passed': isConnectorPassed(index) }"
            aria-hidden="true"
          >
            <svg viewBox="0 0 20 10" width="20" height="10">
              <path d="M1 5h15" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
              <path d="M12.5 1.8 18 5l-5.5 3.2" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
        </template>
      </div>
    </div>

    <button
      v-else
      class="workflow-stage-toggle-btn"
      type="button"
      :aria-label="isCollapsed ? '展开流程图' : '折叠流程图'"
      :title="isCollapsed ? '展开流程图' : '折叠流程图'"
      @click="toggleCollapsed"
    >
      <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
        <path
          v-if="!isCollapsed"
          d="M2.5 7.8 6 4.2l3.5 3.6"
          fill="none"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <path
          v-else
          d="M2.5 4.2 6 7.8l3.5-3.6"
          fill="none"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  steps: {
    type: Array,
    default: () => []
  }
});

const safeSteps = computed(() => (Array.isArray(props.steps) ? props.steps : []));
const isCollapsed = ref(false);

const activeStepIndex = computed(() => {
  const source = safeSteps.value;
  if (!source.length) return -1;

  const activeIdx = source.findIndex((item) => normalizeStatus(item?.status) === 'active');
  if (activeIdx >= 0) return activeIdx;

  const pausedIdx = source.findIndex((item) => normalizeStatus(item?.status) === 'paused');
  if (pausedIdx >= 0) return pausedIdx;

  const failedIdx = source.findIndex((item) => normalizeStatus(item?.status) === 'failed');
  if (failedIdx >= 0) return failedIdx;

  const pendingIdx = source.findIndex((item) => normalizeStatus(item?.status) === 'pending');
  if (pendingIdx > 0) return pendingIdx - 1;

  return source.length - 1;
});

const currentStep = computed(() => {
  const source = safeSteps.value;
  const idx = activeStepIndex.value;
  if (idx < 0 || idx >= source.length) return null;
  return source[idx];
});

const currentStepKey = computed(() => {
  const step = currentStep.value;
  if (!step) return '';
  return resolveStepKey(step, activeStepIndex.value);
});

function normalizeStatus(rawStatus) {
  const status = String(rawStatus || '').trim().toLowerCase();
  if (status === 'running' || status === 'doing') return 'active';
  if (status === 'done' || status === 'completed' || status === 'skipped') return 'done';
  if (status === 'action_required') return 'paused';
  if (status === 'failed' || status === 'error' || status === 'fallback') return 'failed';
  return 'pending';
}

function statusText(rawStatus) {
  const status = normalizeStatus(rawStatus);
  if (status === 'active') return '进行中';
  if (status === 'done') return '已完成';
  if (status === 'paused') return '待确认';
  if (status === 'failed') return '失败';
  return '准备中';
}

function resolveStepKey(step, index) {
  const key = String(step?.key || '').trim();
  if (key) return key;
  return `stage-${Math.max(0, Number(index) || 0)}`;
}

function resolveShape(step, index) {
  const key = String(step?.key || '').trim().toLowerCase();
  if (key.includes('checkpoint') || key === 'checkpoint') return 'diamond';
  if (key === 'graph' || key.includes('graph')) return 'hexagon';
  if (key === 'retrieve' || key.includes('search')) return 'rounded';

  const fallback = ['rounded', 'diamond', 'hexagon'];
  return fallback[index % fallback.length];
}

function isConnectorPassed(index) {
  const source = safeSteps.value;
  if (!source.length) return false;
  const leftStatus = normalizeStatus(source[index]?.status);
  if (leftStatus === 'done') return true;
  return activeStepIndex.value > index;
}

function toggleCollapsed() {
  isCollapsed.value = !isCollapsed.value;
}
</script>

<style scoped>
.workflow-stage-strip {
  min-height: 0;
  display: grid;
  align-content: start;
}

.workflow-stage-strip.is-collapsed {
  display: flex;
  justify-content: flex-end;
  align-items: center;
}

.workflow-stage-toggle-btn {
  justify-self: end;
  width: 20px;
  height: 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  margin-bottom: 4px;
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background-color 0.2s ease;
}

.workflow-stage-toggle-btn:hover {
  border-color: var(--line-2);
  color: var(--text);
  background: var(--panel);
}

.workflow-stage-toggle-btn:focus-visible {
  outline: 1px solid var(--line-2);
  outline-offset: 1px;
}

.workflow-stage-strip.is-collapsed .workflow-stage-toggle-btn {
  margin-bottom: 0;
}

.workflow-stage-panel {
  position: relative;
  min-height: 72px;
  padding: 10px 12px;
}

.workflow-stage-panel .workflow-stage-toggle-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  margin-bottom: 0;
  z-index: 2;
}

.workflow-stage-flow {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 2px 28px 2px 2px;
  width: 100%;
  scrollbar-width: thin;
}

.workflow-stage-node {
  position: relative;
  flex: 0 0 126px;
  width: 126px;
  height: 50px;
  --node-border: var(--line);
  --node-bg: var(--panel);
}

.workflow-stage-node-frame {
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: var(--radius-sm);
  background: linear-gradient(var(--node-border), var(--node-border));
  transition: background-color 0.2s ease;
}

.workflow-stage-node-frame::before {
  content: '';
  position: absolute;
  inset: 1px;
  border-radius: inherit;
  background: var(--node-bg);
  transition: background-color 0.2s ease;
}

.workflow-stage-node.shape-rounded .workflow-stage-node-frame {
  border-radius: var(--radius-md);
}

.workflow-stage-node.shape-diamond {
  flex-basis: 102px;
  width: 102px;
}

.workflow-stage-node.shape-diamond .workflow-stage-node-frame {
  clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%);
  border-radius: 0;
}

.workflow-stage-node.shape-diamond .workflow-stage-node-frame::before {
  clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%);
  border-radius: 0;
}

.workflow-stage-node.shape-hexagon .workflow-stage-node-frame {
  clip-path: polygon(11% 0, 89% 0, 100% 50%, 89% 100%, 11% 100%, 0 50%);
  border-radius: 0;
}

.workflow-stage-node.shape-hexagon .workflow-stage-node-frame::before {
  clip-path: polygon(11% 0, 89% 0, 100% 50%, 89% 100%, 11% 100%, 0 50%);
  border-radius: 0;
}

.workflow-stage-node.shape-parallelogram .workflow-stage-node-frame {
  clip-path: polygon(9% 0, 100% 0, 91% 100%, 0 100%);
  border-radius: 0;
}

.workflow-stage-node.shape-parallelogram .workflow-stage-node-frame::before {
  clip-path: polygon(9% 0, 100% 0, 91% 100%, 0 100%);
  border-radius: 0;
}

.workflow-stage-node-content {
  position: relative;
  z-index: 1;
  height: 100%;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 1px;
  padding: 0 8px;
  text-align: center;
}

.workflow-stage-node-index {
  margin: 0;
  font-size: 9px;
  line-height: 1;
  color: var(--muted);
}

.workflow-stage-node-label {
  margin: 0;
  max-width: 100%;
  font-size: 11px;
  line-height: 1.15;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.workflow-stage-node-status {
  margin: 0;
  font-size: 9px;
  line-height: 1;
  color: var(--muted);
  white-space: nowrap;
}

.workflow-stage-node.is-current {
  --node-border: var(--line-2);
  --node-bg: var(--bg);
}

.workflow-stage-node.is-done {
  --node-border: var(--success);
}

.workflow-stage-node.is-done .workflow-stage-node-status {
  color: var(--success);
}

.workflow-stage-node.is-active {
  --node-border: var(--text);
}

.workflow-stage-node.is-active .workflow-stage-node-status {
  color: var(--text);
}

.workflow-stage-node.is-failed {
  --node-border: var(--accent);
}

.workflow-stage-node.is-failed .workflow-stage-node-status {
  color: var(--accent);
}

.workflow-stage-node.is-paused .workflow-stage-node-status {
  color: var(--text);
}

.workflow-stage-connector {
  flex: 0 0 20px;
  width: 20px;
  height: 10px;
  color: var(--muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: color 0.2s ease;
}

.workflow-stage-connector.is-passed {
  color: var(--success);
}

@media (max-width: 768px) {
  .workflow-stage-panel {
    min-height: auto;
    padding: 10px;
  }

  .workflow-stage-node {
    flex-basis: 112px;
    width: 112px;
    height: 48px;
  }

  .workflow-stage-node.shape-diamond {
    flex-basis: 94px;
    width: 94px;
  }

  .workflow-stage-flow {
    justify-content: flex-start;
  }
}
</style>
