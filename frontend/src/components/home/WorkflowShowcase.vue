<template>
  <section class="panel workflow-shell" :class="{ 'is-collapsed': started }">
    <div class="workflow-head">
      <div class="workflow-brand">
        <img class="workflow-logo" src="/assets/brand/logo-light.png" alt="StarFish logo" />
      </div>
      <p
        :key="`workflow-tagline-${locale}`"
        class="workflow-tagline workflow-tagline-typing muted"
        data-i18n-skip="true"
      >
        {{ localizedTagline }}
      </p>
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
      <div v-if="!started" class="workflow-start-wrap">
        <button
          ref="startButtonRef"
          class="btn btn-accent mono workflow-start-btn"
          :class="{ 'is-auto-clicking': handTapActive }"
          type="button"
          @click="handleStartClick"
        >
          开始
        </button>
      </div>
    </div>

    <div
      v-if="showGuideHand && !started"
      class="workflow-guide-hand"
      :class="{ 'is-moving': handMoveActive, 'is-tapping': handTapActive }"
      :style="guideHandStyle"
      aria-hidden="true"
    >
      <svg class="workflow-guide-hand-icon" viewBox="0 0 24 24" fill="none">
        <path d="M9 12.2V5.8a1.6 1.6 0 1 1 3.2 0v4.8" />
        <path d="M12.2 9.1V4.8a1.6 1.6 0 1 1 3.2 0v6.1" />
        <path d="M5.8 12.8V8.7a1.6 1.6 0 1 1 3.2 0" />
        <path d="M15.4 10.7V7.6a1.6 1.6 0 1 1 3.2 0v5.8a5.8 5.8 0 0 1-5.8 5.8h-2.5a5.8 5.8 0 0 1-4.9-2.6L4 14.7" />
      </svg>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { useRuntimeLocale } from '../../i18n/runtime';

const { isEnglish, locale } = useRuntimeLocale();

const localizedTagline = computed(() => {
  return isEnglish.value
    ? 'A multi-agent research engine for retrieval, graphs, and exploration.'
    : '从一个研究领域向多触角延展，集检索、建图、自主探索的科研工作引擎。';
});

const emit = defineEmits(['start']);

const props = defineProps({
  steps: {
    type: Array,
    required: true
  },
  started: {
    type: Boolean,
    required: true
  },
  autoStart: {
    type: Boolean,
    default: true
  }
});

const showGuideHand = ref(false);
const handMoveActive = ref(false);
const handTapActive = ref(false);
const startButtonRef = ref(null);
const guideTimerIds = [];
const guideHandPath = ref({
  startX: 0,
  startY: 0,
  deltaX: 0,
  deltaY: 0
});
const TAGLINE_TYPING_CYCLE_MS = 6200;
const GUIDE_DELAY_AFTER_TYPING_MS = 2000;
const GUIDE_HAND_SIZE = 36;
const GUIDE_HAND_MARGIN = 24;

const guideHandStyle = computed(() => {
  return {
    '--guide-hand-start-x': `${Math.round(guideHandPath.value.startX)}px`,
    '--guide-hand-start-y': `${Math.round(guideHandPath.value.startY)}px`,
    '--guide-hand-delta-x': `${Math.round(guideHandPath.value.deltaX)}px`,
    '--guide-hand-delta-y': `${Math.round(guideHandPath.value.deltaY)}px`
  };
});

function clearGuideTimers() {
  while (guideTimerIds.length) {
    const timerId = guideTimerIds.pop();
    clearTimeout(timerId);
  }
}

function resetGuideState() {
  showGuideHand.value = false;
  handMoveActive.value = false;
  handTapActive.value = false;
}

function handleStartClick() {
  clearGuideTimers();
  resetGuideState();
  emit('start');
}

function resolveGuideHandPath() {
  if (typeof window === 'undefined') return false;
  const button = startButtonRef.value;
  if (!button) return false;
  const rect = button.getBoundingClientRect();
  if (!Number.isFinite(rect.left) || rect.width <= 0 || rect.height <= 0) return false;
  const startX = Math.max(
    GUIDE_HAND_MARGIN,
    window.innerWidth - GUIDE_HAND_SIZE - GUIDE_HAND_MARGIN
  );
  const startY = Math.max(
    GUIDE_HAND_MARGIN,
    window.innerHeight - GUIDE_HAND_SIZE - GUIDE_HAND_MARGIN
  );
  const endX = rect.left + rect.width / 2 - GUIDE_HAND_SIZE / 2;
  const endY = rect.top + rect.height / 2 - GUIDE_HAND_SIZE / 2;
  guideHandPath.value = {
    startX,
    startY,
    deltaX: endX - startX,
    deltaY: endY - startY
  };
  return true;
}

function playAutoGuide() {
  clearGuideTimers();
  resetGuideState();
  if (props.started || !props.autoStart || !startButtonRef.value) return;

  const reduceMotion = typeof window !== 'undefined'
    && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
  const guideStartDelay = reduceMotion ? 240 : (TAGLINE_TYPING_CYCLE_MS + GUIDE_DELAY_AFTER_TYPING_MS);

  guideTimerIds.push(
    setTimeout(() => {
      if (!resolveGuideHandPath()) return;
      showGuideHand.value = true;
    }, guideStartDelay)
  );
  guideTimerIds.push(
    setTimeout(() => {
      handMoveActive.value = true;
    }, guideStartDelay + (reduceMotion ? 50 : 120))
  );
  guideTimerIds.push(
    setTimeout(() => {
      handTapActive.value = true;
    }, guideStartDelay + (reduceMotion ? 130 : 980))
  );
  guideTimerIds.push(
    setTimeout(() => {
      handleStartClick();
    }, guideStartDelay + (reduceMotion ? 210 : 1250))
  );
}

watch(
  () => [props.started, props.autoStart],
  ([started, autoStart]) => {
    if (started || !autoStart) {
      clearGuideTimers();
      resetGuideState();
      return;
    }
    playAutoGuide();
  }
);

onBeforeUnmount(() => {
  clearGuideTimers();
  resetGuideState();
});

onMounted(() => {
  nextTick(() => {
    playAutoGuide();
  });
});
</script>
