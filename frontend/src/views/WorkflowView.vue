<template>
  <section class="workflow-page">
    <div class="workflow-layout">
      <article class="workflow-left">
        <LoadingState v-if="graphLoading" :message="activeStepHint" />
        <ErrorBoundary v-else-if="errorMessage" :message="errorMessage" />
        <KnowledgeGraphView v-else-if="graphData" :graph-data="graphData" />
        <section v-else class="panel workflow-empty">
          <p class="muted">等待工作流执行...</p>
        </section>
      </article>

      <aside class="workflow-right panel">
        <div class="panel-head">
          <h2>工作流</h2>
          <button class="btn mono" type="button" @click="$emit('back')">返回输入页</button>
        </div>
        <div class="workflow-step-list">
          <article
            v-for="step in steps"
            :key="step.index"
            class="workflow-step-item"
            :class="`is-${step.status}`"
          >
            <p class="workflow-step-index mono">{{ String(step.index).padStart(2, '0') }}</p>
            <div class="workflow-step-content">
              <p class="workflow-step-title">{{ step.title }}</p>
              <p class="workflow-step-desc muted">{{ step.description }}</p>
              <p v-if="step.message" class="workflow-step-message mono">{{ step.message }}</p>
            </div>
          </article>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';

import { buildKnowledgeGraph, getKnowledgeGraph } from '../api';
import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import KnowledgeGraphView from '../components/graph/KnowledgeGraphView.vue';
import LoadingState from '../components/common/LoadingState.vue';

const props = defineProps({
  seed: {
    type: Object,
    required: true
  }
});

const emit = defineEmits(['step-change', 'back']);

const steps = ref([
  { index: 1, title: '论文检索', description: '检索与当前输入相关的论文集合。', status: 'pending', message: '' },
  { index: 2, title: '图构建', description: '构建论文、实体与关系图结构。', status: 'pending', message: '' },
  { index: 3, title: '实体关系抽取', description: '从标题与摘要抽取实体并关联。', status: 'pending', message: '' },
  { index: 4, title: 'Neo4j 落库', description: '将图谱写入 Neo4j（可用时）。', status: 'pending', message: '' },
  { index: 5, title: '可视化展示', description: '在前端渲染图谱关系网络。', status: 'pending', message: '' }
]);

const graphLoading = ref(false);
const graphData = ref(null);
const errorMessage = ref('');

const activeStep = computed(() => {
  const running = steps.value.find((item) => item.status === 'running');
  if (running) return running;

  const failed = steps.value.find((item) => item.status === 'failed');
  if (failed) return failed;

  const done = [...steps.value].reverse().find((item) => ['done', 'skipped'].includes(item.status));
  return done || steps.value[0];
});

const activeStepHint = computed(() => activeStep.value?.description || '工作流运行中...');

function updateStepSignal() {
  emit('step-change', {
    index: activeStep.value.index,
    total: steps.value.length,
    title: activeStep.value.title
  });
}

function setStepStatus(index, status, message = '') {
  const target = steps.value.find((item) => item.index === index);
  if (!target) return;
  target.status = status;
  target.message = message;
  updateStepSignal();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function runWorkflow() {
  errorMessage.value = '';
  graphLoading.value = true;

  try {
    setStepStatus(1, 'running', '正在检索论文...');
    await sleep(260);
    setStepStatus(1, 'done', '已完成论文检索。');

    setStepStatus(2, 'running', '正在构建图结构...');
    const result = await buildKnowledgeGraph({
      query: props.seed.input_value,
      max_papers: 12,
      max_entities_per_paper: 6
    });
    setStepStatus(2, 'done', `${result.paper_count} 篇论文已建图。`);

    setStepStatus(3, 'running', '正在抽取实体关系...');
    await sleep(180);
    setStepStatus(3, 'done', `${result.entity_count} 个实体已抽取。`);

    setStepStatus(4, 'running', '正在写入 Neo4j...');
    await sleep(120);
    let resolvedGraph = result;
    if (result.stored_in_neo4j) {
      try {
        resolvedGraph = await getKnowledgeGraph(result.graph_id);
        setStepStatus(4, 'done', '已写入并从 Neo4j 回读。');
      } catch (neo4jReadError) {
        setStepStatus(4, 'done', '已写入 Neo4j，回读失败，已使用实时结果。');
      }
    } else {
      setStepStatus(4, 'skipped', 'Neo4j 不可用，已跳过落库。');
    }

    setStepStatus(5, 'running', '正在渲染前端图谱...');
    graphData.value = resolvedGraph;
    await sleep(120);
    setStepStatus(5, 'done', '图谱展示完成。');
  } catch (error) {
    const failed = activeStep.value?.index || 2;
    setStepStatus(failed, 'failed', '步骤执行失败。');
    errorMessage.value = error.message || '工作流执行失败。';
  } finally {
    graphLoading.value = false;
    updateStepSignal();
  }
}

onMounted(async () => {
  updateStepSignal();
  await runWorkflow();
});
</script>
