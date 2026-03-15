<template>
  <section class="seed-workspace home-two-layer" :class="{ 'is-started': isInputVisible }">
    <WorkflowShowcase :steps="workflowSteps" :started="isInputVisible" @start="handleStartClick" />

    <form v-if="isInputVisible && canUseFeatures" class="seed-input-shell panel" @submit.prevent="startAnalysis">
      <div class="seed-input-row">
        <div class="seed-mode-picker" ref="modePickerRef">
          <button
            id="input-type"
            class="seed-mode-trigger mono"
            type="button"
            :disabled="!canUseFeatures"
            aria-label="选择研究模式"
            :aria-expanded="modeMenuOpen ? 'true' : 'false'"
            @click="toggleModeMenu"
          >
            <span class="seed-mode-trigger-label" :class="{ 'is-placeholder': !hasInputType }">
              {{ modeTriggerLabel }}
            </span>
            <span class="seed-mode-caret" aria-hidden="true">▾</span>
          </button>
          <div v-if="modeMenuOpen" class="seed-mode-menu panel" role="listbox">
            <div class="seed-mode-option-group" @mouseenter="openPaperSubmenu">
              <button
                class="seed-mode-option seed-mode-option-next mono"
                :class="{ 'is-selected': selectedMode === 'paper_id' }"
                type="button"
                @click="togglePaperSubmenu"
              >
                <span>论文 ID</span>
                <span class="seed-mode-next-arrow" aria-hidden="true">›</span>
              </button>
              <div v-if="paperSubmenuOpen" class="seed-mode-submenu panel" role="listbox">
                <button
                  v-for="option in paperIdTypeOptions"
                  :key="`paper-${option.value}`"
                  class="seed-mode-option mono"
                  :class="{ 'is-selected': selectedMode === 'paper_id' && String(mapInput.input_type || '') === option.value }"
                  type="button"
                  @click="selectPaperType(option.value)"
                >
                  {{ option.label }}
                </button>
              </div>
            </div>
            <div class="seed-mode-option-group" @mouseenter="openDomainSubmenu">
              <button
                class="seed-mode-option seed-mode-option-next mono"
                :class="{ 'is-selected': selectedMode === 'domain' }"
                type="button"
                @click="toggleDomainSubmenu"
              >
                <span>领域研究</span>
                <span class="seed-mode-next-arrow" aria-hidden="true">›</span>
              </button>
              <div v-if="domainSubmenuOpen" class="seed-mode-submenu panel" role="listbox">
                <button
                  v-for="option in paperRangeOptions"
                  :key="`range-${option.value}`"
                  class="seed-mode-option mono"
                  :class="{ 'is-selected': isDomainInput && String(mapInput.paper_range_years || '') === option.value }"
                  type="button"
                  @click="selectDomainRange(option.value)"
                >
                  {{ option.label }}
                </button>
              </div>
            </div>
          </div>
        </div>
        <div class="seed-query-field" :class="{ 'is-disabled': !hasInputType || !canUseFeatures }">
          <input
            id="input-value"
            class="seed-text-input mono"
            v-model="mapInput.input_value"
            :placeholder="currentInputMeta.placeholder"
            :disabled="!hasInputType || !canUseFeatures"
          />
          <div class="seed-strategy-picker" ref="strategyPickerRef">
            <button
              class="seed-strategy-trigger mono"
              :class="{ 'is-disabled': !isStrategyAvailable || !canUseFeatures }"
              type="button"
              :disabled="!isStrategyAvailable || !canUseFeatures"
              :aria-expanded="strategyMenuOpen ? 'true' : 'false'"
              aria-label="选择检索模式"
              @click="toggleStrategyMenu"
            >
              <span class="seed-strategy-icon" aria-hidden="true">
                <svg
                  v-if="selectedStrategyKey === 'quick'"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z" />
                </svg>
                <svg
                  v-else
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M12 2a7 7 0 0 0-4 12c1 1 1.5 2 1.7 3h4.6c.2-1 .7-2 1.7-3A7 7 0 0 0 12 2z" />
                  <path d="M9 18h6" />
                  <path d="M10 22h4" />
                </svg>
              </span>
              <span>{{ selectedStrategyLabel }}</span>
              <span class="seed-strategy-caret" aria-hidden="true">▾</span>
            </button>
            <div v-if="strategyMenuOpen" class="seed-strategy-menu panel" role="listbox">
              <button
                class="seed-strategy-option mono"
                :class="{ 'is-selected': !mapInput.quick_mode }"
                type="button"
                @click="selectStrategy('normal')"
              >
                <span class="seed-strategy-icon" aria-hidden="true">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <path d="M12 2a7 7 0 0 0-4 12c1 1 1.5 2 1.7 3h4.6c.2-1 .7-2 1.7-3A7 7 0 0 0 12 2z" />
                    <path d="M9 18h6" />
                    <path d="M10 22h4" />
                  </svg>
                </span>
                <span>普通模式</span>
              </button>
              <button
                class="seed-strategy-option mono"
                :class="{ 'is-selected': mapInput.quick_mode }"
                type="button"
                @click="selectStrategy('quick')"
              >
                <span class="seed-strategy-icon" aria-hidden="true">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z" />
                  </svg>
                </span>
                <span>快速模式</span>
              </button>
            </div>
          </div>
        </div>
        <div class="seed-actions">
          <button
            class="btn btn-accent mono seed-submit-btn"
            type="submit"
            :disabled="!canUseFeatures || !String(mapInput.input_type || '').trim() || !mapInput.input_value.trim()"
          >
            开始分析
          </button>
        </div>
      </div>
    </form>

    <article v-else-if="isInputVisible" class="seed-auth-card panel">
      <p class="seed-auth-card-kicker mono">Authentication</p>
      <p class="seed-auth-card-title">请先登录再开始分析</p>
      <GoogleAuthStatus />
    </article>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import GoogleAuthStatus from '../components/common/GoogleAuthStatus.vue';
import WorkflowShowcase from '../components/home/WorkflowShowcase.vue';
import { useMapStore } from '../stores/mapStore';

const props = defineProps({
  canUseFeatures: {
    type: Boolean,
    default: false
  }
});
const emit = defineEmits(['start-analysis']);

const workflowSteps = [
  { key: 'retrieval', title: '知识检索', detail: '聚合论文、数据与背景资料，形成可用语料。' },
  { key: 'graph', title: '图谱构建', detail: '抽取实体关系并连接上下文，生成结构化知识网络。' },
  { key: 'explore', title: '领域地图探索', detail: '识别主干主题、空白区域与关键分叉方向。' },
  { key: 'suggestion', title: '生成研究建议', detail: '输出可执行的选题建议与后续推进路径。' }
];

const paperRangeOptions = [
  { label: '所有时间', value: '' },
  { label: '近 1 年', value: '1' },
  { label: '近 3 年', value: '3' },
  { label: '近 5 年', value: '5' },
  { label: '近 10 年', value: '10' }
];
const paperIdTypeOptions = [
  { label: 'arXiv ID', value: 'arxiv_id' },
  { label: 'DOI ID', value: 'doi' }
];

const isInputVisible = ref(false);
const { mapInput } = useMapStore();
const modePickerRef = ref(null);
const strategyPickerRef = ref(null);
const modeMenuOpen = ref(false);
const paperSubmenuOpen = ref(false);
const domainSubmenuOpen = ref(false);
const strategyMenuOpen = ref(false);
const inputTypeMeta = {
  arxiv_id: {
    placeholder: '例如：2301.07041',
    hint: '输入 arXiv ID，构建以该论文为中心的知识图谱。'
  },
  doi: {
    placeholder: '例如：10.1145/3442188.3445922',
    hint: '输入 DOI ID，构建以该论文为中心的知识图谱。'
  },
  domain: {
    placeholder: '例如：transformer、深度强化学习、多模态大模型',
    hint: '输入研究领域，生成子方向、核心论文与趋势洞察全景图。'
  }
};
const currentInputMeta = computed(
  () => inputTypeMeta[mapInput.value.input_type] || { placeholder: '请先选择研究模式', hint: '' }
);
const selectedMode = computed(() => {
  const type = String(mapInput.value.input_type || '').trim();
  if (type === 'domain') return 'domain';
  if (type === 'arxiv_id' || type === 'doi') return 'paper_id';
  return '';
});
const hasInputType = computed(() => Boolean(String(mapInput.value.input_type || '').trim()));
const isDomainInput = computed(() => String(mapInput.value.input_type || '').trim() === 'domain');
const isStrategyAvailable = computed(() => hasInputType.value);
const selectedStrategyKey = computed(() => (mapInput.value.quick_mode ? 'quick' : 'normal'));
const selectedStrategyLabel = computed(() => (mapInput.value.quick_mode ? '快速模式' : '普通模式'));
const selectedPaperTypeLabel = computed(() => {
  const selected = paperIdTypeOptions.find((item) => item.value === String(mapInput.value.input_type || ''));
  return selected?.label || paperIdTypeOptions[0].label;
});
const selectedRangeLabel = computed(() => {
  const selected = paperRangeOptions.find((item) => item.value === String(mapInput.value.paper_range_years || ''));
  return selected?.label || paperRangeOptions[0].label;
});
const modeTriggerLabel = computed(() => {
  if (selectedMode.value === 'paper_id') return selectedPaperTypeLabel.value;
  if (selectedMode.value === 'domain') return `领域研究 · ${selectedRangeLabel.value}`;
  return '选择研究模式';
});
const canUseFeatures = computed(() => Boolean(props.canUseFeatures));

function handleStartClick() {
  isInputVisible.value = true;
}

function toggleModeMenu() {
  if (!canUseFeatures.value) return;
  modeMenuOpen.value = !modeMenuOpen.value;
  if (modeMenuOpen.value) {
    paperSubmenuOpen.value = false;
    domainSubmenuOpen.value = false;
    closeStrategyMenu();
  }
}

function closeModeMenu() {
  modeMenuOpen.value = false;
  paperSubmenuOpen.value = false;
  domainSubmenuOpen.value = false;
}

function toggleStrategyMenu() {
  if (!canUseFeatures.value || !isStrategyAvailable.value) return;
  strategyMenuOpen.value = !strategyMenuOpen.value;
  if (strategyMenuOpen.value) {
    closeModeMenu();
  }
}

function closeStrategyMenu() {
  strategyMenuOpen.value = false;
}

function openPaperSubmenu() {
  if (!canUseFeatures.value) return;
  paperSubmenuOpen.value = true;
  domainSubmenuOpen.value = false;
}

function togglePaperSubmenu() {
  if (!canUseFeatures.value) return;
  paperSubmenuOpen.value = !paperSubmenuOpen.value;
  domainSubmenuOpen.value = false;
}

function selectPaperType(nextType) {
  if (!canUseFeatures.value) return;
  mapInput.value.input_type = String(nextType || '').trim() === 'doi' ? 'doi' : 'arxiv_id';
  closeModeMenu();
}

function openDomainSubmenu() {
  if (!canUseFeatures.value) return;
  mapInput.value.input_type = 'domain';
  paperSubmenuOpen.value = false;
  domainSubmenuOpen.value = true;
}

function toggleDomainSubmenu() {
  if (!canUseFeatures.value) return;
  mapInput.value.input_type = 'domain';
  paperSubmenuOpen.value = false;
  domainSubmenuOpen.value = !domainSubmenuOpen.value;
}

function selectDomainRange(rangeValue) {
  if (!canUseFeatures.value) return;
  mapInput.value.input_type = 'domain';
  mapInput.value.paper_range_years = String(rangeValue ?? '');
  closeModeMenu();
}

function selectStrategy(nextMode) {
  if (!canUseFeatures.value || !isStrategyAvailable.value) return;
  mapInput.value.quick_mode = nextMode === 'quick';
  closeStrategyMenu();
}

function handleDocumentClick(event) {
  const target = event.target;
  if (!modePickerRef.value?.contains(event.target)) {
    closeModeMenu();
  }
  if (!strategyPickerRef.value?.contains(target)) {
    closeStrategyMenu();
  }
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    closeModeMenu();
    closeStrategyMenu();
  }
}

function parsePaperRangeYears(rawValue) {
  const parsed = Number.parseInt(String(rawValue || '').trim(), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.min(30, parsed);
}

function startAnalysis() {
  if (!canUseFeatures.value) return;
  const selectedInputType = String(mapInput.value.input_type || '').trim();
  const value = mapInput.value.input_value.trim();
  if (!selectedInputType || !value) return;
  const paperRangeYears = isDomainInput.value
    ? parsePaperRangeYears(mapInput.value.paper_range_years)
    : null;
  emit('start-analysis', {
    input_type: selectedInputType,
    input_value: value,
    paper_range_years: paperRangeYears,
    quick_mode: Boolean(mapInput.value.quick_mode),
    depth: mapInput.value.depth || 2
  });
}

watch(
  canUseFeatures,
  (enabled) => {
    if (!enabled) {
      closeModeMenu();
      closeStrategyMenu();
    }
  }
);

onMounted(() => {
  document.addEventListener('mousedown', handleDocumentClick);
  document.addEventListener('keydown', handleKeydown);
});

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleDocumentClick);
  document.removeEventListener('keydown', handleKeydown);
});
</script>
