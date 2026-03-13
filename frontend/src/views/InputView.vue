<template>
  <section class="seed-workspace home-two-layer" :class="{ 'is-started': isInputVisible }">
    <WorkflowShowcase :steps="workflowSteps" :started="isInputVisible" @start="isInputVisible = true" />

    <form v-if="isInputVisible" class="seed-input-shell panel" @submit.prevent="startAnalysis">
      <div class="seed-input-row">
        <CustomSelect
          id="input-type"
          v-model="mapInput.input_type"
          :options="inputTypeOptions"
          aria-label="选择输入类型"
        />
        <input
          id="input-value"
          class="seed-text-input mono"
          v-model="mapInput.input_value"
          :placeholder="currentInputMeta.placeholder"
        />
        <button class="btn btn-accent mono seed-submit-btn" type="submit" :disabled="!mapInput.input_value.trim()">
          开始分析
        </button>
      </div>
      <p class="seed-input-hint mono muted">{{ currentInputMeta.hint }}</p>
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
  { label: 'PDF 链接', value: 'pdf' },
  { label: '研究领域', value: 'domain' }
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
  pdf: {
    placeholder: '例如：https://arxiv.org/pdf/1706.03762.pdf',
    hint: '输入 PDF 链接，系统将提取论文元信息并开始检索。'
  },
  domain: {
    placeholder: '例如：transformer、深度强化学习、多模态大模型',
    hint: '输入研究领域，生成子方向、核心论文与趋势洞察全景图。'
  }
};
const currentInputMeta = computed(
  () => inputTypeMeta[mapInput.value.input_type] || inputTypeMeta.arxiv_id
);

function startAnalysis() {
  const value = mapInput.value.input_value.trim();
  if (!value) return;
  emit('start-analysis', {
    input_type: mapInput.value.input_type,
    input_value: value,
    depth: mapInput.value.depth || 2
  });
}
</script>
