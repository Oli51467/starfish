<template>
  <button
    class="header-lang-toggle"
    type="button"
    :aria-label="toggleLabel"
    :title="toggleLabel"
    data-i18n-skip="true"
    @click="toggleLocale"
  >
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.3" />
      <circle cx="8" cy="8" r="2.6" fill="currentColor" />
    </svg>
    <span class="mono">{{ isEnglish ? '中' : 'EN' }}</span>
  </button>
</template>

<script setup>
import { computed } from 'vue';

import { useRuntimeLocale } from '../../i18n/runtime';

const { isEnglish, toggleLocale } = useRuntimeLocale();

const toggleLabel = computed(() => {
  return isEnglish.value ? '切换为中文' : 'Switch to English';
});
</script>
