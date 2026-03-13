<template>
  <aside class="workflow-right">
    <div class="workflow-step-list">
      <article
        v-for="step in steps"
        :key="step.index"
        class="workflow-step-item"
        :class="`is-${step.status}`"
      >
        <p class="workflow-step-index mono">{{ String(step.index).padStart(2, '0') }}</p>
        <div class="workflow-step-content">
          <div class="workflow-step-head">
            <p class="workflow-step-title">{{ step.title }}</p>
            <span class="workflow-trace-badge" :class="`is-${stepBadgeStatus(step.status)}`">
              {{ stepBadgeText(step.status) }}
            </span>
          </div>
          <p class="workflow-step-desc muted">{{ step.description }}</p>
          <p v-if="step.message" class="workflow-step-message mono">{{ step.message }}</p>

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
        </div>
      </article>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  steps: {
    type: Array,
    default: () => []
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
</script>
