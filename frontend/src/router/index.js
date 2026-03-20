import { createRouter, createWebHistory } from 'vue-router';

import { useAuthStore } from '../stores/authStore';
import HomeView from '../views/HomeView.vue';
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
    path: '/research/paper/lineage',
    name: 'research-paper-lineage',
    component: HomeView,
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

router.beforeEach(async (to) => {
  if (!to.meta?.requiresAuth) return true;

  const authStore = useAuthStore();
  await authStore.loadSession();
  if (authStore.isAuthenticated.value) {
    return true;
  }
  return { name: 'home' };
});

export default router;
