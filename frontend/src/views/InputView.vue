<template>
  <section class="seed-workspace home-two-layer" :class="{ 'is-started': isInputVisible }">
    <WorkflowShowcase :steps="workflowSteps" :started="isInputVisible" @start="isInputVisible = true" />

    <form v-if="isInputVisible" class="seed-input-shell panel" @submit.prevent="startAnalysis">
      <div class="seed-input-row">
        <CustomSelect
          id="input-type"
          v-model="mapInput.input_type"
          :options="inputTypeOptions"
          placeholder="选择研究方向"
          aria-label="选择输入类型"
        />
        <input
          id="input-value"
          class="seed-text-input mono"
          v-model="mapInput.input_value"
          :placeholder="currentInputMeta.placeholder"
          :disabled="!hasInputType"
        />
        <CustomSelect
          id="paper-range"
          class="seed-range-select"
          v-model="mapInput.paper_range_years"
          :options="paperRangeOptions"
          aria-label="选择论文范围"
        />
        <button
          class="btn btn-accent mono seed-submit-btn"
          type="submit"
          :disabled="!String(mapInput.input_type || '').trim() || !mapInput.input_value.trim()"
        >
          开始分析
        </button>
      </div>
    </form>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';

import CustomSelect from '../components/common/CustomSelect.vue';
import WorkflowShowcase from '../components/home/WorkflowShowcase.vue';
import { useMapStore } from '../stores/mapStore';

const emit = defineEmits(['start-analysis']);

const workflowSteps = [
  { key: 'retrieval', title: '知识检索', detail: '聚合论文、数据与背景资料，形成可用语料。' },
  { key: 'graph', title: '图谱构建', detail: '抽取实体关系并连接上下文，生成结构化知识网络。' },
  { key: 'explore', title: '领域地图探索', detail: '识别主干主题、空白区域与关键分叉方向。' },
  { key: 'suggestion', title: '生成研究建议', detail: '输出可执行的选题建议与后续推进路径。' }
];

const inputTypeOptions = [
  { label: 'arXiv ID', value: 'arxiv_id' },
  { label: 'DOI', value: 'doi' },
  { label: '领域研究', value: 'domain' }
];
const paperRangeOptions = [
  { label: '所有时间', value: '' },
  { label: '近 1 年', value: '1' },
  { label: '近 3 年', value: '3' },
  { label: '近 5 年', value: '5' },
  { label: '近 10 年', value: '10' }
];

const isInputVisible = ref(false);
const { mapInput } = useMapStore();
const inputTypeMeta = {
  arxiv_id: {
    placeholder: '例如：2301.07041',
    hint: '输入 arXiv ID，构建以该论文为中心的知识图谱。'
  },
  doi: {
    placeholder: '例如：10.1145/3442188.3445922',
    hint: '输入 DOI，自动补全元数据并构建论文关系图。'
  },
  domain: {
    placeholder: '例如：transformer、深度强化学习、多模态大模型',
    hint: '输入研究领域，生成子方向、核心论文与趋势洞察全景图。'
  }
};
const currentInputMeta = computed(
  () => inputTypeMeta[mapInput.value.input_type] || { placeholder: '请先选择研究方向', hint: '' }
);
const hasInputType = computed(() => Boolean(String(mapInput.value.input_type || '').trim()));

function parsePaperRangeYears(rawValue) {
  const parsed = Number.parseInt(String(rawValue || '').trim(), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.min(30, parsed);
}

function startAnalysis() {
  const inputType = String(mapInput.value.input_type || '').trim();
  const value = mapInput.value.input_value.trim();
  if (!inputType || !value) return;
  emit('start-analysis', {
    input_type: inputType,
    input_value: value,
    paper_range_years: parsePaperRangeYears(mapInput.value.paper_range_years),
    depth: mapInput.value.depth || 2
  });
}
</script>
