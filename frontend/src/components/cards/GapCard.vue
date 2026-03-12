<template>
  <article class="card gap-card">
    <div class="card-head">
      <p class="card-title">{{ gap.title }}</p>
      <span class="mono">{{ gap.opportunity_score }}/100</span>
    </div>
    <p class="mono muted">{{ gap.type }}</p>
    <p class="card-text">{{ gap.description }}</p>
  </article>
</template>

<script setup>
defineProps({
  gap: {
    type: Object,
    required: true
  }
});
</script>
