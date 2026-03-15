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
      <InputView v-if="!workflowActive" :can-use-features="isAuthenticated" @start-analysis="enterWorkflow" />
      <LandscapeView
        v-else-if="isDomainWorkflow"
        :query="workflowSeed.input_value"
        :paper-range-years="workflowSeed.paper_range_years"
        :quick-mode="workflowSeed.quick_mode"
        @step-change="updateHeaderStep"
      />
      <WorkflowView v-else :seed="workflowSeed" @step-change="updateHeaderStep" @back="exitWorkflow" />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';

import AppHeader from '../components/layout/AppHeader.vue';
import { useAuthStore } from '../stores/authStore';
import InputView from './InputView.vue';
import LandscapeView from './LandscapeView.vue';
import WorkflowView from './WorkflowView.vue';

const workflowActive = ref(false);
const workflowSeed = ref({
  input_type: '',
  input_value: '',
  paper_range_years: null,
  quick_mode: false,
  depth: 2
});
const headerStep = ref({
  index: 1,
  total: 2,
  title: '论文检索'
});
const isDomainWorkflow = computed(() => workflowSeed.value.input_type === 'domain');
const { isAuthenticated, loadSession } = useAuthStore();

function enterWorkflow(payload) {
  if (!isAuthenticated.value) return;

  workflowSeed.value = { ...payload };
  const isDomain = payload.input_type === 'domain';
  headerStep.value = {
    index: 1,
    total: isDomain ? 4 : 2,
    title: isDomain ? '领域调研' : '论文检索'
  };
  workflowActive.value = true;
}

function updateHeaderStep(payload) {
  headerStep.value = {
    index: payload.index || 1,
    total: payload.total || headerStep.value.total || 2,
    title: payload.title || '论文检索'
  };
}

function exitWorkflow() {
  workflowActive.value = false;
}

watch(isAuthenticated, (next) => {
  if (!next && workflowActive.value) {
    workflowActive.value = false;
  }
});

onMounted(() => {
  void loadSession();
});
</script>
