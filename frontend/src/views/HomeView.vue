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
      <WorkflowView
        v-else
        :seed="workflowSeed"
        :result-view="paperResultView"
        @step-change="updateHeaderStep"
        @result-view-change="handleWorkflowResultViewChange"
        @lineage-availability-change="handleLineageAvailabilityChange"
        @back="exitWorkflow"
      />
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
const paperResultView = ref('graph');
const paperLineageEnabled = ref(false);
const isDomainWorkflow = computed(() => workflowSeed.value.input_type === 'domain');
const { isAuthenticated, loadSession } = useAuthStore();

function enterWorkflow(payload) {
  if (!isAuthenticated.value) return;

  workflowSeed.value = { ...payload };
  const isDomain = payload.input_type === 'domain';
  headerStep.value = {
    index: 1,
    total: isDomain ? 4 : 3,
    title: isDomain ? '领域调研' : '论文检索'
  };
  paperResultView.value = 'graph';
  paperLineageEnabled.value = false;
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
  paperResultView.value = 'graph';
  paperLineageEnabled.value = false;
}

function handleWorkflowResultViewChange(nextView) {
  const normalized = String(nextView || '').trim().toLowerCase();
  if (normalized === 'lineage' && !paperLineageEnabled.value) {
    paperResultView.value = 'graph';
    return;
  }
  paperResultView.value = normalized === 'lineage' ? 'lineage' : 'graph';
}

function handleLineageAvailabilityChange(enabled) {
  paperLineageEnabled.value = Boolean(enabled);
  if (!paperLineageEnabled.value && paperResultView.value === 'lineage') {
    paperResultView.value = 'graph';
  }
}

watch(isAuthenticated, (next) => {
  if (!next && workflowActive.value) {
    workflowActive.value = false;
    paperResultView.value = 'graph';
    paperLineageEnabled.value = false;
  }
});

onMounted(() => {
  void loadSession();
});
</script>
