<template>
  <div class="loading-block" role="status" aria-live="polite">
    <span class="loading-dot" aria-hidden="true"></span>
    <p class="mono">{{ message }}</p>
  </div>
</template>

<script setup>
defineProps({
  message: {
    type: String,
    default: '处理中...'
  }
});
</script>
