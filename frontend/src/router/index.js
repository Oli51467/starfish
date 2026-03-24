import { createRouter, createWebHistory } from 'vue-router';

import { useAuthStore } from '../stores/authStore';
import { useGlobalConfirmDialog } from '../composables/useGlobalConfirmDialog';
import HomeView from '../views/HomeView.vue';
import WorkflowView from '../views/WorkflowView.vue';
import LandscapeView from '../views/LandscapeView.vue';
import MapView from '../views/MapView.vue';
import ReadingListView from '../views/ReadingListView.vue';
import GapFinderView from '../views/GapFinderView.vue';
import CollectionWorkbenchView from '../views/CollectionWorkbenchView.vue';
import ResearchHistoryView from '../views/ResearchHistoryView.vue';

const routes = [
  {
    path: '/',
    name: 'home',
    component: HomeView
  },
  {
    path: '/research/domain/graph',
    name: 'research-domain-graph',
    component: HomeView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/research/paper/graph',
    name: 'research-paper-graph',
    component: HomeView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/research/pipeline',
    name: 'research-pipeline',
    component: WorkflowView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/landscape',
    name: 'landscape',
    component: LandscapeView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/map',
    name: 'map',
    component: MapView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/reading-list',
    name: 'reading-list',
    component: ReadingListView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/gap-finder',
    name: 'gap-finder',
    component: GapFinderView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/research-history',
    name: 'research-history',
    component: ResearchHistoryView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/collections',
    name: 'collection-workbench',
    component: CollectionWorkbenchView,
    meta: {
      requiresAuth: true
    }
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

const WORKFLOW_ROUTE_NAMES = new Set([
  'research-domain-graph',
  'research-paper-graph',
  'research-pipeline'
]);
const ACTIVE_RESEARCH_SESSION_STORAGE_KEY = 'starfish:active-research-session';
const TERMINAL_SESSION_STATUSES = new Set(['completed', 'failed', 'stopped', 'error', 'cancelled', 'canceled']);
let leaveWorkflowConfirmPending = false;

function normalizeActiveSessionFromStorage(payload = {}) {
  const source = payload?.session && typeof payload.session === 'object' ? payload.session : payload;
  const sessionId = String(source?.session_id || '').trim();
  const status = String(source?.status || '').trim().toLowerCase();
  return {
    sessionId,
    status
  };
}

function hasRunningWorkflowSession() {
  if (typeof window === 'undefined') return false;
  try {
    const raw = window.localStorage.getItem(ACTIVE_RESEARCH_SESSION_STORAGE_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    const normalized = normalizeActiveSessionFromStorage(parsed || {});
    if (!normalized.sessionId) return false;
    if (!normalized.status) return true;
    return !TERMINAL_SESSION_STATUSES.has(normalized.status);
  } catch {
    return false;
  }
}

function shouldConfirmLeavingWorkflow(to, from) {
  const fromName = String(from?.name || '').trim();
  const toName = String(to?.name || '').trim();
  if (!WORKFLOW_ROUTE_NAMES.has(fromName)) return false;
  if (WORKFLOW_ROUTE_NAMES.has(toName)) return false;
  return hasRunningWorkflowSession();
}

router.beforeEach(async (to, from) => {
  if (to.meta?.requiresAuth) {
    const authStore = useAuthStore();
    await authStore.loadSession();
    if (!authStore.isAuthenticated.value) {
      return { name: 'home' };
    }
  }

  if (shouldConfirmLeavingWorkflow(to, from)) {
    if (leaveWorkflowConfirmPending) return false;
    leaveWorkflowConfirmPending = true;
    try {
      const { askForConfirm } = useGlobalConfirmDialog();
      const confirmed = await askForConfirm({
        title: '任务仍在执行',
        message: '当前工作流正在后台执行，离开后可在首页继续查看进度。是否继续跳转？',
        confirmText: '继续离开',
        cancelText: '留在当前页'
      });
      if (!confirmed) {
        return false;
      }
    } finally {
      leaveWorkflowConfirmPending = false;
    }
  }

  return true;
});

export default router;
