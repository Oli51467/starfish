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
      <template v-if="!workflowActive">
        <InputView :can-use-features="isAuthenticated" @start-analysis="enterWorkflow" />
        <aside
          v-if="activeSessionNotice"
          class="active-session-notice panel"
          role="button"
          tabindex="0"
          @click="resumeActiveSessionWorkflow"
          @keydown.enter.prevent="resumeActiveSessionWorkflow"
          @keydown.space.prevent="resumeActiveSessionWorkflow"
        >
          <p class="active-session-notice-kicker mono">进行中任务</p>
          <p class="active-session-notice-title">{{ activeSessionNoticeTitle }}</p>
          <p class="active-session-notice-detail">
            {{ activeSessionNoticeDetail }}
          </p>
        </aside>
      </template>
      <WorkflowView
        v-else
        :seed="workflowSeed"
        @step-change="updateHeaderStep"
        @back="exitWorkflow"
      />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { getActiveResearchSession } from '../api';
import AppHeader from '../components/layout/AppHeader.vue';
import { useAuthStore } from '../stores/authStore';
import InputView from './InputView.vue';
import WorkflowView from './WorkflowView.vue';

const workflowActive = ref(false);
const workflowSeed = ref({
  input_type: '',
  input_value: '',
  paper_range_years: null,
  quick_mode: true,
  depth: 2,
  runtime_session_id: ''
});
const headerStep = ref({
  index: 1,
  total: 3,
  title: '论文检索'
});
const activeSessionNotice = ref(null);
const { isAuthenticated, loadSession, accessToken } = useAuthStore();
const router = useRouter();
const route = useRoute();
const WORKFLOW_SEED_STORAGE_KEY = 'starfish:workflow-seed';
const ACTIVE_SESSION_STORAGE_KEY = 'starfish:active-research-session';
const COMPLETED_WORKFLOW_SNAPSHOT_STORAGE_KEY = 'starfish:workflow-completed-snapshot';

const WORKFLOW_ROUTE_NAMES = new Set([
  'research-domain-graph',
  'research-paper-graph'
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

function parseBooleanLike(value, defaultValue = false) {
  if (value === undefined || value === null || value === '') {
    return Boolean(defaultValue);
  }
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
  return {
    input_type: inputType,
    input_value: inputValue,
    paper_range_years: inputType === 'domain'
      ? parseOptionalPositiveInteger(payload.paper_range_years)
      : null,
    quick_mode: parseBooleanLike(payload.quick_mode, true),
    depth: parseOptionalPositiveInteger(payload.depth) || 2,
    runtime_session_id: normalizeText(payload.runtime_session_id)
  };
}

function toPersistableWorkflowSeed(seed = {}) {
  return normalizeWorkflowSeed(seed);
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

function clearCompletedWorkflowSnapshotCache() {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(COMPLETED_WORKFLOW_SNAPSHOT_STORAGE_KEY);
  } catch {
    // ignore storage remove failures
  }
}

function clearActiveSessionNotice() {
  activeSessionNotice.value = null;
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
  } catch {
    // ignore storage remove failures
  }
}

function persistActiveSessionNotice(payload) {
  if (!payload || typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // ignore storage write failures
  }
}

function restoreActiveSessionNotice() {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return normalizeActiveSessionNotice(parsed);
  } catch {
    return null;
  }
}

function normalizeActiveSessionNotice(payload = {}) {
  const source = payload?.session && typeof payload.session === 'object'
    ? payload.session
    : payload;
  const sessionId = normalizeText(source?.session_id);
  if (!sessionId) return null;
  return {
    session_id: sessionId,
    status: normalizeText(source?.status).toLowerCase() || 'running',
    progress: Math.max(0, Math.min(100, Number(source?.progress || 0) || 0)),
    current_node: normalizeText(source?.current_node),
    waiting_checkpoint: normalizeText(source?.waiting_checkpoint),
    input_type: normalizeText(source?.input_type).toLowerCase() || 'domain',
    input_value: normalizeText(source?.input_value),
    paper_range_years: parseOptionalPositiveInteger(source?.paper_range_years),
    quick_mode: parseBooleanLike(source?.quick_mode, true),
    updated_at: normalizeText(source?.updated_at)
  };
}

async function refreshActiveSessionNotice({ allowLocalFallback = true } = {}) {
  if (!isAuthenticated.value) {
    clearActiveSessionNotice();
    return;
  }
  try {
    const payload = await getActiveResearchSession({ accessToken: accessToken.value || '' });
    const hasActive = Boolean(payload?.has_active_session);
    const notice = hasActive ? normalizeActiveSessionNotice(payload?.session) : null;
    if (notice) {
      activeSessionNotice.value = notice;
      persistActiveSessionNotice(notice);
      return;
    }
    clearActiveSessionNotice();
  } catch {
    if (!allowLocalFallback) {
      clearActiveSessionNotice();
      return;
    }
    const localNotice = restoreActiveSessionNotice();
    if (localNotice) {
      activeSessionNotice.value = localNotice;
      return;
    }
    clearActiveSessionNotice();
  }
}

function resolveInputTypeLabel(inputType) {
  const normalized = normalizeText(inputType).toLowerCase();
  if (normalized === 'domain') return '领域检索';
  if (normalized === 'doi') return 'DOI 检索';
  return '论文检索';
}

const activeSessionNoticeTitle = computed(() => {
  if (!activeSessionNotice.value) return '检测到进行中任务';
  return `${resolveInputTypeLabel(activeSessionNotice.value.input_type)}仍在执行`;
});

const activeSessionNoticeDetail = computed(() => {
  if (!activeSessionNotice.value) return '';
  const inputValue = normalizeText(activeSessionNotice.value.input_value);
  const progress = Number(activeSessionNotice.value.progress || 0);
  const progressText = Number.isFinite(progress) ? `${Math.max(0, Math.min(100, Math.round(progress)))}%` : '进行中';
  if (!inputValue) return `任务进度：${progressText}`;
  return `目标：${inputValue} · 进度 ${progressText}`;
});

function applyHeaderForSeed(seed) {
  headerStep.value = {
    index: 1,
    total: 3,
    title: seed.input_type === 'domain' ? '领域调研' : '论文检索'
  };
}

function resolveWorkflowRouteName() {
  if (!workflowActive.value) return 'home';
  if (workflowSeed.value.input_type === 'domain') return 'research-domain-graph';
  return 'research-paper-graph';
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
}

function isSeedCompatibleWithRoute(seed, routeName) {
  if (!seed) return false;
  if (routeName === 'research-domain-graph') {
    return seed.input_type === 'domain';
  }
  if (routeName === 'research-paper-graph') {
    return seed.input_type !== 'domain';
  }
  return true;
}

function parseRouteSeed(routeName, queryPayload = {}) {
  if (!WORKFLOW_ROUTE_NAMES.has(routeName)) return null;
  if (routeName === 'research-domain-graph') {
    const query = normalizeText(queryPayload.query || queryPayload.input_value);
    if (!query) return null;
    return normalizeWorkflowSeed({
      input_type: 'domain',
      input_value: query,
      paper_range_years: queryPayload.paper_range_years,
      quick_mode: queryPayload.quick_mode,
      depth: queryPayload.depth,
      runtime_session_id: queryPayload.runtime_session_id
    });
  }

  const paperId = normalizeText(queryPayload.paper_id || queryPayload.paperId || queryPayload.input_value);
  if (!paperId) return null;
  const routeInputType = normalizeText(queryPayload.input_type).toLowerCase();
  const inputType = routeInputType === 'doi' || routeInputType === 'arxiv_id'
    ? routeInputType
    : detectPaperInputType(paperId);
  return normalizeWorkflowSeed({
    input_type: inputType,
    input_value: paperId,
    quick_mode: queryPayload.quick_mode,
    depth: queryPayload.depth,
    runtime_session_id: queryPayload.runtime_session_id
  });
}

async function applyRouteToWorkflow() {
  if (syncingRoute) return;
  const routeName = String(route.name || '');

  if (routeName === 'home') {
    if (workflowActive.value) {
      resetWorkflowState();
    }
    if (isAuthenticated.value) {
      await refreshActiveSessionNotice();
    } else {
      clearActiveSessionNotice();
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
  activeSessionNotice.value = null;
  if (routeSeed) {
    persistWorkflowSeed(routeSeed);
  }
  applyHeaderForSeed(seed);
  workflowActive.value = true;
}

async function enterWorkflow(payload) {
  if (!isAuthenticated.value) return;
  await refreshActiveSessionNotice({ allowLocalFallback: false });
  if (activeSessionNotice.value) {
    return;
  }

  clearCompletedWorkflowSnapshotCache();
  workflowSeed.value = normalizeWorkflowSeed(payload);
  if (!workflowSeed.value.input_value) return;
  persistWorkflowSeed(workflowSeed.value);
  applyHeaderForSeed(workflowSeed.value);
  activeSessionNotice.value = null;
  workflowActive.value = true;
  await syncRouteFromWorkflow({ replace: false });
}

async function resumeActiveSessionWorkflow() {
  const active = activeSessionNotice.value;
  if (!active) return;

  clearCompletedWorkflowSnapshotCache();
  workflowSeed.value = normalizeWorkflowSeed({
    input_type: active.input_type,
    input_value: active.input_value,
    paper_range_years: active.paper_range_years,
    quick_mode: active.quick_mode,
    runtime_session_id: active.session_id
  });
  persistWorkflowSeed(workflowSeed.value);
  applyHeaderForSeed(workflowSeed.value);
  activeSessionNotice.value = null;
  workflowActive.value = true;
  await syncRouteFromWorkflow({ replace: false });
}

function updateHeaderStep(payload) {
  headerStep.value = {
    index: payload.index || 1,
    total: payload.total || headerStep.value.total || 2,
    title: payload.title || '论文检索'
  };
}

async function exitWorkflow() {
  await router.push({ name: 'home' });
  if (String(route.name || '') === 'home') {
    clearPersistedWorkflowSeed();
  }
}

watch(isAuthenticated, (next) => {
  if (!next && workflowActive.value) {
    resetWorkflowState();
    clearPersistedWorkflowSeed();
    void syncRouteFromWorkflow();
  }
  if (!next) {
    clearActiveSessionNotice();
    return;
  }
  if (!workflowActive.value) {
    void refreshActiveSessionNotice();
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

watch(
  () => workflowActive.value,
  (active) => {
    if (active) {
      activeSessionNotice.value = null;
      return;
    }
    if (isAuthenticated.value) {
      void refreshActiveSessionNotice();
    }
  }
);

onMounted(async () => {
  await loadSession();
  await applyRouteToWorkflow();
  if (!workflowActive.value && isAuthenticated.value) {
    await refreshActiveSessionNotice();
  }
});
</script>

<style scoped>
.active-session-notice {
  position: fixed;
  right: 14px;
  top: 82px;
  width: min(252px, calc(100vw - 28px));
  border: 1px solid var(--line-2);
  background: var(--bg);
  padding: 8px 10px;
  display: grid;
  gap: 4px;
  cursor: pointer;
  transition: border-color 0.2s ease, background-color 0.2s ease;
  z-index: 8;
}

.active-session-notice:hover {
  border-color: var(--accent);
  background: var(--panel);
}

.active-session-notice:focus-visible {
  outline: 0;
  border-color: var(--accent);
}

.active-session-notice-kicker {
  margin: 0;
  font-size: 10px;
  line-height: 1.3;
  color: var(--muted);
}

.active-session-notice-title {
  margin: 0;
  font-size: 11px;
  line-height: 1.4;
  color: var(--text);
  font-weight: 600;
}

.active-session-notice-detail {
  margin: 0;
  font-size: 10px;
  line-height: 1.4;
  color: var(--text);
  word-break: break-word;
}

@media (max-width: 768px) {
  .active-session-notice {
    top: 68px;
    right: 10px;
    width: min(228px, calc(100vw - 20px));
  }
}
</style>
