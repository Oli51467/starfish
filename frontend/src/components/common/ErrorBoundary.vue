<template>
  <div class="error-block" v-if="message">
    <p class="mono">{{ message }}</p>
  </div>
</template>

<script setup>
defineProps({
  message: {
    type: String,
    default: ''
  }
});
</script>
