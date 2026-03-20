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
      <PipelineView
        v-else-if="isPipelineWorkflow"
        :seed="workflowSeed"
        @step-change="updateHeaderStep"
      />
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
import { useRoute, useRouter } from 'vue-router';

import AppHeader from '../components/layout/AppHeader.vue';
import { useAuthStore } from '../stores/authStore';
import InputView from './InputView.vue';
import LandscapeView from './LandscapeView.vue';
import PipelineView from './PipelineView.vue';
import WorkflowView from './WorkflowView.vue';

const workflowActive = ref(false);
const workflowSeed = ref({
  input_type: '',
  input_value: '',
  paper_range_years: null,
  quick_mode: false,
  workflow_mode: 'manual',
  depth: 2,
  auto_lineage: false,
  lineage_seed_paper_id: ''
});
const headerStep = ref({
  index: 1,
  total: 2,
  title: '论文检索'
});
const paperResultView = ref('graph');
const paperLineageEnabled = ref(false);
const isDomainWorkflow = computed(() => workflowSeed.value.input_type === 'domain');
const isPipelineWorkflow = computed(() => workflowSeed.value.workflow_mode === 'pipeline');
const { isAuthenticated, loadSession } = useAuthStore();
const router = useRouter();
const route = useRoute();
const WORKFLOW_SEED_STORAGE_KEY = 'starfish:workflow-seed';

const WORKFLOW_ROUTE_NAMES = new Set([
  'research-domain-graph',
  'research-paper-graph',
  'research-paper-lineage',
  'research-pipeline'
]);

function normalizeText(value) {
  return String(value || '').trim();
}

function detectPaperInputType(paperId) {
  const safePaperId = normalizeText(paperId);
  if (!safePaperId) return 'arxiv_id';
  const normalized = safePaperId.toLowerCase();
  if (/10\.\d{4,9}\/\S+/i.test(safePaperId) || normalized.includes('doi.org/')) {
    return 'doi';
  }
  return 'arxiv_id';
}

function parseBooleanLike(value) {
  if (typeof value === 'boolean') return value;
  const normalized = normalizeText(value).toLowerCase();
  return ['1', 'true', 'yes', 'y', 'on'].includes(normalized);
}

function parseOptionalPositiveInteger(value) {
  const parsed = Number.parseInt(normalizeText(value), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return parsed;
}

function normalizeWorkflowSeed(payload = {}) {
  const normalizedInputType = normalizeText(payload.input_type).toLowerCase();
  const inputType = normalizedInputType === 'domain'
    ? 'domain'
    : (normalizedInputType === 'doi' ? 'doi' : 'arxiv_id');
  const inputValue = normalizeText(payload.input_value);
  const workflowMode = normalizeText(payload.workflow_mode).toLowerCase() === 'pipeline'
    ? 'pipeline'
    : 'manual';
  return {
    input_type: inputType,
    input_value: inputValue,
    paper_range_years: inputType === 'domain'
      ? parseOptionalPositiveInteger(payload.paper_range_years)
      : null,
    quick_mode: parseBooleanLike(payload.quick_mode),
    workflow_mode: workflowMode,
    depth: parseOptionalPositiveInteger(payload.depth) || 2,
    auto_lineage: parseBooleanLike(payload.auto_lineage),
    lineage_seed_paper_id: normalizeText(payload.lineage_seed_paper_id)
  };
}

function toPersistableWorkflowSeed(seed = {}) {
  const normalized = normalizeWorkflowSeed(seed);
  return {
    ...normalized,
    auto_lineage: false,
    lineage_seed_paper_id: ''
  };
}

function persistWorkflowSeed(seed) {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(
      WORKFLOW_SEED_STORAGE_KEY,
      JSON.stringify(toPersistableWorkflowSeed(seed || {}))
    );
  } catch {
    // ignore storage write failures
  }
}

function restoreWorkflowSeed() {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(WORKFLOW_SEED_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const normalized = normalizeWorkflowSeed(parsed || {});
    if (!normalized.input_value) return null;
    return normalized;
  } catch {
    return null;
  }
}

function clearPersistedWorkflowSeed() {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(WORKFLOW_SEED_STORAGE_KEY);
  } catch {
    // ignore storage remove failures
  }
}

function applyHeaderForSeed(seed) {
  if (seed.workflow_mode === 'pipeline') {
    headerStep.value = {
      index: 1,
      total: 9,
      title: 'Pipeline'
    };
    return;
  }
  headerStep.value = {
    index: 1,
    total: 4,
    title: seed.input_type === 'domain' ? '领域调研' : '论文检索'
  };
}

function resolveWorkflowRouteName() {
  if (!workflowActive.value) return 'home';
  if (workflowSeed.value.workflow_mode === 'pipeline') return 'research-pipeline';
  if (workflowSeed.value.input_type === 'domain') return 'research-domain-graph';
  return paperResultView.value === 'lineage'
    ? 'research-paper-lineage'
    : 'research-paper-graph';
}

let syncingRoute = false;

async function syncRouteFromWorkflow({ replace = true } = {}) {
  const targetName = resolveWorkflowRouteName();
  if (String(route.name || '') === targetName) {
    return;
  }
  syncingRoute = true;
  try {
    if (replace) {
      await router.replace({ name: targetName });
    } else {
      await router.push({ name: targetName });
    }
  } finally {
    syncingRoute = false;
  }
}

function resetWorkflowState() {
  workflowActive.value = false;
  paperResultView.value = 'graph';
  paperLineageEnabled.value = false;
}

function isSeedCompatibleWithRoute(seed, routeName) {
  if (!seed) return false;
  if (routeName === 'research-pipeline') {
    return seed.workflow_mode === 'pipeline';
  }
  if (routeName === 'research-domain-graph') {
    if (seed.workflow_mode === 'pipeline') return false;
    return seed.input_type === 'domain';
  }
  if (routeName === 'research-paper-graph' || routeName === 'research-paper-lineage') {
    if (seed.workflow_mode === 'pipeline') return false;
    return seed.input_type !== 'domain';
  }
  return true;
}

function parseRouteSeed(routeName, queryPayload = {}) {
  if (!WORKFLOW_ROUTE_NAMES.has(routeName)) return null;
  if (routeName === 'research-pipeline') {
    const inputValue = normalizeText(
      queryPayload.input_value || queryPayload.query || queryPayload.paper_id || queryPayload.paperId
    );
    if (!inputValue) return null;
    const normalizedInputType = normalizeText(queryPayload.input_type).toLowerCase();
    const inputType = ['domain', 'doi', 'arxiv_id'].includes(normalizedInputType)
      ? normalizedInputType
      : detectPaperInputType(inputValue);
    return normalizeWorkflowSeed({
      workflow_mode: 'pipeline',
      input_type: inputType,
      input_value: inputValue,
      paper_range_years: queryPayload.paper_range_years,
      quick_mode: queryPayload.quick_mode,
      depth: queryPayload.depth
    });
  }
  if (routeName === 'research-domain-graph') {
    const query = normalizeText(queryPayload.query || queryPayload.input_value);
    if (!query) return null;
    return normalizeWorkflowSeed({
      workflow_mode: 'manual',
      input_type: 'domain',
      input_value: query,
      paper_range_years: queryPayload.paper_range_years,
      quick_mode: queryPayload.quick_mode,
      depth: queryPayload.depth
    });
  }

  const paperId = normalizeText(queryPayload.paper_id || queryPayload.paperId || queryPayload.input_value);
  if (!paperId) return null;
  const routeInputType = normalizeText(queryPayload.input_type).toLowerCase();
  const inputType = routeInputType === 'doi' || routeInputType === 'arxiv_id'
    ? routeInputType
    : detectPaperInputType(paperId);
  return normalizeWorkflowSeed({
    workflow_mode: 'manual',
    input_type: inputType,
    input_value: paperId,
    quick_mode: queryPayload.quick_mode,
    depth: queryPayload.depth,
    auto_lineage: queryPayload.auto_lineage,
    lineage_seed_paper_id: normalizeText(queryPayload.lineage_seed_paper_id || paperId)
  });
}

async function applyRouteToWorkflow() {
  if (syncingRoute) return;
  const routeName = String(route.name || '');

  if (routeName === 'home') {
    if (workflowActive.value) {
      resetWorkflowState();
    }
    return;
  }

  if (!WORKFLOW_ROUTE_NAMES.has(routeName)) return;

  if (!isAuthenticated.value) {
    resetWorkflowState();
    clearPersistedWorkflowSeed();
    await router.replace({ name: 'home' });
    return;
  }

  const routeSeed = parseRouteSeed(routeName, route.query || {});
  const restoredSeed = restoreWorkflowSeed();
  const seed = routeSeed || restoredSeed;
  if (!seed || !isSeedCompatibleWithRoute(seed, routeName)) {
    resetWorkflowState();
    clearPersistedWorkflowSeed();
    await router.replace({ name: 'home' });
    return;
  }

  workflowSeed.value = seed;
  if (routeSeed) {
    persistWorkflowSeed(routeSeed);
  }
  applyHeaderForSeed(seed);
  workflowActive.value = true;

  if (routeName === 'research-paper-lineage') {
    paperResultView.value = 'lineage';
  } else {
    paperResultView.value = 'graph';
  }
}

async function enterWorkflow(payload) {
  if (!isAuthenticated.value) return;

  workflowSeed.value = normalizeWorkflowSeed(payload);
  if (!workflowSeed.value.input_value) return;
  persistWorkflowSeed(workflowSeed.value);
  applyHeaderForSeed(workflowSeed.value);
  paperResultView.value = 'graph';
  paperLineageEnabled.value = false;
  workflowActive.value = true;
  await syncRouteFromWorkflow({ replace: false });
}

function updateHeaderStep(payload) {
  headerStep.value = {
    index: payload.index || 1,
    total: payload.total || headerStep.value.total || 2,
    title: payload.title || (workflowSeed.value.workflow_mode === 'pipeline' ? 'Pipeline' : '论文检索')
  };
}

async function exitWorkflow() {
  resetWorkflowState();
  clearPersistedWorkflowSeed();
  await syncRouteFromWorkflow({ replace: false });
}

async function handleWorkflowResultViewChange(nextView) {
  const normalized = String(nextView || '').trim().toLowerCase();
  if (normalized === 'lineage' && !paperLineageEnabled.value) {
    paperResultView.value = 'graph';
    await syncRouteFromWorkflow();
    return;
  }
  paperResultView.value = normalized === 'lineage' ? 'lineage' : 'graph';
  await syncRouteFromWorkflow();
}

async function handleLineageAvailabilityChange(enabled) {
  paperLineageEnabled.value = Boolean(enabled);
  if (!paperLineageEnabled.value && paperResultView.value === 'lineage') {
    paperResultView.value = 'graph';
    await syncRouteFromWorkflow();
  }
}

watch(isAuthenticated, (next) => {
  if (!next && workflowActive.value) {
    resetWorkflowState();
    clearPersistedWorkflowSeed();
    void syncRouteFromWorkflow();
  }
});

watch(
  () => workflowSeed.value,
  (nextSeed) => {
    if (!workflowActive.value) return;
    persistWorkflowSeed(nextSeed);
  },
  { deep: true }
);

watch(
  () => route.fullPath,
  () => {
    void applyRouteToWorkflow();
  }
);

onMounted(async () => {
  await loadSession();
  await applyRouteToWorkflow();
});
</script>
