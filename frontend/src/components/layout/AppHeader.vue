<template>
  <header class="header">
    <div class="header-left">
      <button
        v-if="showBack"
        class="header-back-icon-btn"
        type="button"
        aria-label="返回上一页"
        @click="$emit('back')"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M9.8 3.3a.75.75 0 0 1 0 1.06L6.16 8l3.64 3.64a.75.75 0 1 1-1.06 1.06L4.56 8.53a.75.75 0 0 1 0-1.06L8.74 3.3a.75.75 0 0 1 1.06 0Z" />
        </svg>
      </button>
      <img class="brand-logo" src="/assets/brand/logo-light.png" alt="StarFish logo" />
    </div>

    <div v-if="showBack" class="header-actions">
      <p v-if="showStep" class="mono header-step-inline">
        <span>Step {{ stepIndex }}/{{ stepTotal }} · </span>
        <strong class="header-step-strong">{{ stepTitle }}</strong>
      </p>
      <a
        class="header-github-link mono"
        href="https://github.com/Oli51467/starfish"
        target="_blank"
        rel="noopener noreferrer"
      >
        <svg class="header-github-icon" viewBox="0 0 16 16" aria-hidden="true">
          <path
            d="M8 0C3.58 0 0 3.67 0 8.2c0 3.63 2.29 6.7 5.47 7.78.4.08.55-.18.55-.4 0-.2-.01-.85-.01-1.54-2.22.49-2.69-.98-2.69-.98-.36-.95-.89-1.2-.89-1.2-.73-.51.05-.5.05-.5.81.06 1.24.86 1.24.86.72 1.26 1.88.9 2.34.69.07-.54.28-.9.5-1.11-1.77-.21-3.64-.91-3.64-4.03 0-.89.31-1.61.82-2.18-.08-.21-.36-1.06.08-2.2 0 0 .67-.22 2.2.84A7.4 7.4 0 0 1 8 4.9c.66 0 1.33.09 1.95.27 1.53-1.06 2.2-.84 2.2-.84.44 1.14.16 1.99.08 2.2.51.57.82 1.29.82 2.18 0 3.13-1.88 3.82-3.66 4.03.29.25.54.74.54 1.49 0 1.08-.01 1.95-.01 2.21 0 .22.14.49.55.4A8.2 8.2 0 0 0 16 8.2C16 3.67 12.42 0 8 0Z"
          />
        </svg>
        <span>Github</span>
      </a>
    </div>
  </header>
</template>

<script setup>
defineProps({
  showStep: {
    type: Boolean,
    default: false
  },
  stepIndex: {
    type: Number,
    default: 1
  },
  stepTotal: {
    type: Number,
    default: 5
  },
  stepTitle: {
    type: String,
    default: '论文检索'
  },
  showBack: {
    type: Boolean,
    default: false
  }
});

defineEmits(['back']);
</script>
