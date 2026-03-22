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
      <rect x="2" y="2" width="12" height="12" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.3" />
      <rect x="6" y="6" width="4" height="4" rx="0.8" fill="currentColor" />
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
