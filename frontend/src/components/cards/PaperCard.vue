<template>
  <article class="card paper-card">
    <p class="card-title">{{ paper.title }}</p>
    <p class="mono muted">{{ paper.venue }} · {{ paper.year }} · 引用 {{ paper.citation_count }}</p>
    <p class="card-text">{{ paper.importance_reason }}</p>
  </article>
</template>

<script setup>
defineProps({
  paper: {
    type: Object,
    required: true
  }
});
</script>
