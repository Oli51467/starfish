<template>
  <section class="seed-workspace home-two-layer" :class="{ 'is-started': isInputVisible }">
    <WorkflowShowcase :steps="workflowSteps" :started="isInputVisible" @start="isInputVisible = true" />

    <form v-if="isInputVisible" class="seed-input-shell panel" @submit.prevent="startMapGeneration">
      <div class="seed-input-row">
        <CustomSelect
          id="input-type"
          v-model="mapInput.input_type"
          :options="inputTypeOptions"
          aria-label="选择论文输入类型"
        />
        <input
          id="input-value"
          class="seed-text-input mono"
          v-model="mapInput.input_value"
          placeholder="输入论文标题、摘要、DOI、arXiv ID 或链接"
        />
        <button class="btn btn-accent mono seed-submit-btn" type="submit" :disabled="loading || !mapInput.input_value.trim()">
          {{ loading ? '处理中' : '开始分析' }}
        </button>
      </div>
    </form>

    <ErrorBoundary :message="errorMessage" />
  </section>
</template>

<script setup>
import { ref } from 'vue';

import CustomSelect from '../components/common/CustomSelect.vue';
import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import WorkflowShowcase from '../components/home/WorkflowShowcase.vue';
import { useMapStore } from '../stores/mapStore';

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
  { label: 'GitHub 链接', value: 'github_url' }
];

const isInputVisible = ref(false);

const { mapInput, loading, errorMessage, startMapGeneration } = useMapStore();
</script>
