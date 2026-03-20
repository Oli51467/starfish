<template>
  <section class="pipeline-page">
    <div class="pipeline-layout panel">
      <article class="pipeline-steps panel">
        <header class="pipeline-head">
          <p class="pipeline-title">AutoResearch Pipeline</p>
          <p class="pipeline-subtitle mono">Session {{ sessionId || 'pending' }}</p>
        </header>

        <div class="pipeline-progress">
          <div class="pipeline-progress-bar">
            <div class="pipeline-progress-fill" :style="{ width: `${progress}%` }"></div>
          </div>
          <span class="mono pipeline-progress-text">{{ progress }}%</span>
        </div>

        <div class="pipeline-step-list">
          <article
            v-for="step in steps"
            :key="step.id"
            class="pipeline-step-item"
            :class="`is-${step.status}`"
          >
            <div class="pipeline-step-indicator mono">
              <span v-if="step.status === 'done'">✓</span>
              <span v-else-if="step.status === 'active'">●</span>
              <span v-else-if="step.status === 'paused'">⏸</span>
              <span v-else-if="step.status === 'failed'">!</span>
              <span v-else>○</span>
            </div>
            <div class="pipeline-step-main">
              <p class="pipeline-step-label">{{ step.label }}</p>
              <p v-if="step.summary" class="pipeline-step-summary">{{ step.summary }}</p>
            </div>
          </article>
        </div>
      </article>

      <article class="pipeline-stream panel">
        <header class="pipeline-head">
          <p class="pipeline-title">Agent 推理流</p>
          <p class="pipeline-subtitle mono">{{ currentNode || '-' }}</p>
        </header>

        <section class="pipeline-stream-body">
          <article
            v-for="msg in messages"
            :key="msg.id"
            class="pipeline-stream-message"
          >
            <p class="pipeline-stream-node mono">{{ msg.node || '-' }}</p>
            <p class="pipeline-stream-text">{{ msg.content }}</p>
          </article>

          <article v-if="currentThinking" class="pipeline-stream-message is-thinking">
            <p class="pipeline-stream-node mono">{{ currentNode || '-' }}</p>
            <p class="pipeline-stream-text">
              {{ currentThinking }}
              <span class="pipeline-cursor">▍</span>
            </p>
          </article>
        </section>

        <section v-if="finalReport" class="pipeline-report panel">
          <p class="pipeline-report-title">最终报告</p>
          <pre class="pipeline-report-content">{{ finalReport }}</pre>
        </section>

        <section v-if="isPaused" class="pipeline-checkpoint panel">
          <p class="pipeline-checkpoint-title">检查点</p>
          <p class="pipeline-checkpoint-message">{{ checkpointMessage }}</p>
          <div class="pipeline-checkpoint-actions">
            <button class="btn mono" type="button" @click="resume('')">继续</button>
            <input
              v-model="feedbackInput"
              class="pipeline-feedback-input mono"
              placeholder="输入你的调整意见"
              @keyup.enter="applyFeedback"
            />
            <button class="btn btn-accent mono" type="button" @click="applyFeedback">应用并继续</button>
            <button class="btn mono" type="button" @click="stop">停止</button>
          </div>
          <p v-if="countdown > 0" class="pipeline-countdown mono">{{ countdown }} 秒后自动继续</p>
        </section>

        <section v-if="errorMessage" class="error-block">{{ errorMessage }}</section>
      </article>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue';

import { usePipelineSession } from '../composables/usePipelineSession';
import { useAuthStore } from '../stores/authStore';

const props = defineProps({
  seed: {
    type: Object,
    required: true
  }
});

const emit = defineEmits(['step-change']);

const feedbackInput = ref('');
const { accessToken } = useAuthStore();

const {
  sessionId,
  steps,
  progress,
  messages,
  currentThinking,
  currentNode,
  isPaused,
  checkpointMessage,
  countdown,
  finalReport,
  errorMessage,
  start,
  resume,
  stop,
  refreshReport
} = usePipelineSession({
  accessTokenRef: accessToken,
  onStepChange: (payload) => emit('step-change', payload)
});

function applyFeedback() {
  const feedback = String(feedbackInput.value || '').trim();
  feedbackInput.value = '';
  void resume(feedback);
}

onMounted(async () => {
  await start(props.seed || {});
  await refreshReport();
});
</script>

<style scoped>
.pipeline-page {
  height: calc(100dvh - 110px);
  min-height: calc(100vh - 110px);
}

.pipeline-layout {
  height: 100%;
  display: grid;
  grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
  gap: 10px;
  padding: 10px;
}

.pipeline-steps,
.pipeline-stream {
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--bg);
  min-height: 0;
}

.pipeline-steps {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 10px;
  padding: 12px;
}

.pipeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.pipeline-title {
  margin: 0;
  font-size: 14px;
  color: var(--text);
  font-weight: 600;
}

.pipeline-subtitle {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
}

.pipeline-progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}

.pipeline-progress-bar {
  height: 8px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  overflow: hidden;
}

.pipeline-progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.2s ease;
}

.pipeline-progress-text {
  font-size: 11px;
  color: var(--muted);
}

.pipeline-step-list {
  min-height: 0;
  overflow: auto;
  display: grid;
  gap: 8px;
}

.pipeline-step-item {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  padding: 8px;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 8px;
}

.pipeline-step-item.is-active,
.pipeline-step-item.is-paused {
  border-color: var(--line-2);
  background: var(--bg);
}

.pipeline-step-item.is-failed {
  border-color: var(--accent);
}

.pipeline-step-indicator {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.2;
  padding-top: 2px;
}

.pipeline-step-item.is-active .pipeline-step-indicator {
  color: var(--accent);
}

.pipeline-step-main {
  min-width: 0;
}

.pipeline-step-label {
  margin: 0;
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
}

.pipeline-step-summary {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.4;
}

.pipeline-stream {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto auto;
  gap: 10px;
  padding: 12px;
}

.pipeline-stream-body {
  min-height: 0;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  padding: 10px;
  display: grid;
  gap: 8px;
}

.pipeline-stream-message {
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
}

.pipeline-stream-message:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.pipeline-stream-node {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
}

.pipeline-stream-text {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text);
  line-height: 1.5;
  white-space: pre-wrap;
}

.pipeline-cursor {
  color: var(--accent);
}

.pipeline-report {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  padding: 10px;
}

.pipeline-report-title {
  margin: 0;
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
}

.pipeline-report-content {
  margin: 8px 0 0;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text);
  max-height: 220px;
  overflow: auto;
}

.pipeline-checkpoint {
  border: 1px solid var(--line-2);
  border-radius: var(--radius-sm);
  background: var(--bg);
  padding: 10px;
  display: grid;
  gap: 8px;
}

.pipeline-checkpoint-title {
  margin: 0;
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
}

.pipeline-checkpoint-message {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}

.pipeline-checkpoint-actions {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  gap: 8px;
}

.pipeline-feedback-input {
  width: 100%;
  min-width: 0;
  height: 32px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--text);
  padding: 0 10px;
  font-size: 12px;
}

.pipeline-countdown {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
}

@media (max-width: 980px) {
  .pipeline-page {
    min-height: calc(100dvh - 86px);
    height: auto;
  }

  .pipeline-layout {
    height: auto;
    grid-template-columns: 1fr;
  }

  .pipeline-checkpoint-actions {
    grid-template-columns: 1fr;
  }
}
</style>
