<template>
  <section class="panel workflow-shell" :class="{ 'is-collapsed': started }">
    <div class="workflow-head">
      <p class="mono workflow-kicker">Workflow</p>
      <div class="workflow-brand">
        <img class="workflow-logo" src="/assets/brand/logo-light.png" alt="StarFish logo" />
      </div>
      <p class="muted">从一个研究领域向多触角延展，集检索、建图、自主探索的科研工作引擎。</p>
    </div>

    <ol class="workflow-sequence" :class="{ 'is-active': started }">
      <li
        v-for="(step, index) in steps"
        :key="step.key"
        class="workflow-seq-step"
        :style="{ '--step-delay': `${index * 0.12}s` }"
      >
        <span class="workflow-node mono">{{ String(index + 1).padStart(2, '0') }}</span>
        <article class="workflow-step-card">
          <p class="workflow-title">{{ step.title }}</p>
          <p v-if="step.detail" class="workflow-step-detail muted">{{ step.detail }}</p>
        </article>
      </li>
    </ol>

    <div class="workflow-actions">
      <button v-if="!started" class="btn btn-accent mono workflow-start-btn" type="button" @click="$emit('start')">
        开始
      </button>
    </div>
  </section>
</template>

<script setup>
defineProps({
  steps: {
    type: Array,
    required: true
  },
  started: {
    type: Boolean,
    required: true
  }
});

defineEmits(['start']);
</script>
