<template>
  <header class="header" :class="{ 'is-workflow': showBack }">
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

    <div class="header-actions">
      <div v-if="showResultTabs" class="header-result-tabs" role="tablist" aria-label="结果视图切换">
        <button
          class="header-result-tab mono"
          :class="{ 'is-active': resultView === 'graph' }"
          type="button"
          role="tab"
          :aria-selected="resultView === 'graph'"
          @click="$emit('change-result-view', 'graph')"
        >
          知识图谱
        </button>
        <button
          class="header-result-tab mono"
          :class="{ 'is-active': resultView === 'lineage' }"
          type="button"
          role="tab"
          :aria-selected="resultView === 'lineage'"
          :disabled="!lineageEnabled"
          @click="$emit('change-result-view', 'lineage')"
        >
          血缘树
        </button>
      </div>
      <LanguageToggleButton />
      <p v-if="showBack && showStep" class="mono header-step-inline">
        <span>Step {{ stepIndex }}/{{ stepTotal }} · </span>
        <strong class="header-step-strong">{{ stepTitle }}</strong>
      </p>
      <GoogleAuthStatus v-if="isAuthenticated" />
      <GithubLinkButton />
    </div>
  </header>
</template>

<script setup>
import GithubLinkButton from '../common/GithubLinkButton.vue';
import GoogleAuthStatus from '../common/GoogleAuthStatus.vue';
import LanguageToggleButton from '../common/LanguageToggleButton.vue';
import { useAuthStore } from '../../stores/authStore';

const { isAuthenticated } = useAuthStore();

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
  },
  showResultTabs: {
    type: Boolean,
    default: false
  },
  resultView: {
    type: String,
    default: 'graph'
  },
  lineageEnabled: {
    type: Boolean,
    default: false
  }
});

defineEmits(['back', 'change-result-view']);
</script>
