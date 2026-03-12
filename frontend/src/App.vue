<template>
  <div class="app">
    <AppHeader
      :show-step="workflowActive"
      :step-index="headerStep.index"
      :step-total="headerStep.total"
      :step-title="headerStep.title"
      :show-back="workflowActive"
      @back="exitWorkflow"
    />

    <main class="workspace" :class="workflowActive ? 'workspace-workflow' : 'workspace-single'">
      <InputView v-if="!workflowActive" @start-analysis="enterWorkflow" />
      <WorkflowView v-else :seed="workflowSeed" @step-change="updateHeaderStep" @back="exitWorkflow" />
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue';

import AppHeader from './components/layout/AppHeader.vue';
import InputView from './views/InputView.vue';
import WorkflowView from './views/WorkflowView.vue';

const workflowActive = ref(false);
const workflowSeed = ref({
  input_type: 'arxiv_id',
  input_value: '',
  depth: 2
});
const headerStep = ref({
  index: 1,
  total: 5,
  title: '论文检索'
});

function enterWorkflow(payload) {
  workflowSeed.value = { ...payload };
  headerStep.value = {
    index: 1,
    total: 5,
    title: '论文检索'
  };
  workflowActive.value = true;
}

function updateHeaderStep(payload) {
  headerStep.value = {
    index: payload.index || 1,
    total: payload.total || 5,
    title: payload.title || '论文检索'
  };
}

function exitWorkflow() {
  workflowActive.value = false;
}
</script>
