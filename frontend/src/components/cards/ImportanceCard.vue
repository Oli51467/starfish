<template>
  <article class="card importance-card">
    <p class="result-title mono">{{ layer.label }}</p>
    <p class="card-text">{{ layer.description }}</p>
    <p class="mono muted">论文数：{{ layer.papers?.length || 0 }}</p>
  </article>
</template>

<script setup>
defineProps({
  layer: {
    type: Object,
    required: true
  }
});
</script>
