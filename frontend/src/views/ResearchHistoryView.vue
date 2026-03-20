<template>
  <div class="app">
    <AppHeader :show-back="true" @back="goHome" />

    <main class="workspace workspace-workflow">
      <section class="history-layout">
        <article class="panel history-list-panel">
          <div class="panel-head">
            <h2>研究历史</h2>
            <p class="mono history-count">共 {{ total }} 条</p>
          </div>
          <div class="panel-body">
            <ErrorBoundary v-if="errorMessage && !hasRecords" :message="errorMessage" />
            <LoadingState v-else-if="listLoading" message="正在加载研究历史..." />
            <p v-else-if="!hasRecords" class="muted history-empty">暂无研究记录。</p>
            <div v-else class="history-table-wrap">
              <table class="history-table">
                <thead>
                  <tr>
                    <th>研究类型</th>
                    <th>搜索记录</th>
                    <th>搜索时间</th>
                    <th class="history-actions-head">
                      <div v-if="batchSelectMode" class="history-batch-tools">
                        <button
                          class="history-action-icon-btn"
                          type="button"
                          title="取消多选"
                          aria-label="取消多选"
                          :disabled="batchDeleting"
                          @click.stop="cancelBatchSelectMode"
                          @mousedown.stop
                        >
                          <svg viewBox="0 0 16 16" aria-hidden="true">
                            <path d="M4 4l8 8" />
                            <path d="M12 4L4 12" />
                          </svg>
                        </button>
                        <button
                          class="history-action-icon-btn is-danger"
                          type="button"
                          title="删除所选"
                          aria-label="删除所选"
                          :disabled="selectedCount === 0 || batchDeleting || deletingHistoryId !== '' || listLoading"
                          @click.stop="deleteSelectedRecords"
                          @mousedown.stop
                        >
                          <svg viewBox="0 0 16 16" aria-hidden="true">
                            <path d="M3.5 4.5h9" />
                            <path d="M6.2 4.5v-1a1 1 0 0 1 1-1h1.6a1 1 0 0 1 1 1v1" />
                            <path d="M5.2 6.1v5.3" />
                            <path d="M8 6.1v5.3" />
                            <path d="M10.8 6.1v5.3" />
                            <path d="M4.4 4.5l.5 7a1 1 0 0 0 1 .9h4.2a1 1 0 0 0 1-.9l.5-7" />
                          </svg>
                        </button>
                      </div>
                      <input
                        v-else
                        class="history-check-input"
                        type="checkbox"
                        :checked="false"
                        aria-label="进入多选删除"
                        title="进入多选删除"
                        @click.stop
                        @mousedown.stop
                        @change="enableBatchSelectMode($event.target.checked)"
                      />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in records"
                    :key="item.history_id"
                    :class="{ 'is-active': item.history_id === activeHistoryId }"
                    class="history-row-clickable"
                    role="button"
                    tabindex="0"
                    :aria-label="`查看 ${item.search_record} 的知识图谱`"
                    @click="openDetail(item.history_id)"
                    @keydown.enter.prevent="openDetail(item.history_id)"
                    @keydown.space.prevent="openDetail(item.history_id)"
                  >
                    <td>{{ mapResearchType(item.research_type) }}</td>
                    <td class="history-record-cell" :title="item.search_record">{{ item.search_record }}</td>
                    <td>{{ formatDateTime(item.search_time) }}</td>
                    <td class="history-actions-cell" @click.stop @mousedown.stop>
                      <div class="history-action-slot">
                        <input
                          v-if="batchSelectMode"
                          class="history-check-input"
                          type="checkbox"
                          :checked="isSelected(item.history_id)"
                          :aria-label="`选择 ${item.search_record}`"
                          @click.stop
                          @mousedown.stop
                          @change="toggleRowSelection(item.history_id, $event.target.checked)"
                        />
                        <button
                          v-else
                          class="history-delete-btn"
                          type="button"
                          :disabled="deletingHistoryId === item.history_id || batchDeleting"
                          :aria-label="`删除 ${item.search_record}`"
                          title="删除"
                          @click.stop="deleteRecord(item.history_id)"
                          @mousedown.stop
                          @keydown.enter.stop.prevent
                          @keydown.space.stop.prevent
                        >
                          <svg viewBox="0 0 16 16" aria-hidden="true">
                            <path d="M3.5 4.5h9" />
                            <path d="M6.2 4.5v-1a1 1 0 0 1 1-1h1.6a1 1 0 0 1 1 1v1" />
                            <path d="M5.2 6.1v5.3" />
                            <path d="M8 6.1v5.3" />
                            <path d="M10.8 6.1v5.3" />
                            <path d="M4.4 4.5l.5 7a1 1 0 0 0 1 .9h4.2a1 1 0 0 0 1-.9l.5-7" />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-if="totalPages > 1" class="history-pagination">
              <button class="btn mono" type="button" :disabled="page <= 1 || listLoading" @click="changePage(page - 1)">
                上一页
              </button>
              <span class="mono history-pagination-text">{{ page }} / {{ totalPages }}</span>
              <button
                class="btn mono"
                type="button"
                :disabled="page >= totalPages || listLoading"
                @click="changePage(page + 1)"
              >
                下一页
              </button>
            </div>
          </div>
        </article>

        <article class="panel history-detail-panel">
          <LoadingState v-if="detailLoading" message="正在加载图谱详情..." />
          <p v-else-if="!selectedDetail" class="muted history-empty">请选择一条记录查看知识图谱。</p>
          <div v-else class="history-detail-content">
            <div v-if="showDetailTabs" class="history-detail-tabbar" role="tablist" aria-label="历史详情视图切换">
              <div class="history-detail-tabs">
                <button
                  class="history-detail-tab mono"
                  :class="{ 'is-active': activeDetailTab === 'graph' }"
                  type="button"
                  role="tab"
                  :aria-selected="activeDetailTab === 'graph'"
                  @click="activeDetailTab = 'graph'"
                >
                  知识图谱
                </button>
                <button
                  class="history-detail-tab mono"
                  :class="{ 'is-active': activeDetailTab === 'lineage' }"
                  type="button"
                  role="tab"
                  :aria-selected="activeDetailTab === 'lineage'"
                  @click="activeDetailTab = 'lineage'"
                >
                  血缘树
                </button>
              </div>
            </div>
            <section v-if="showSignalPanel" class="history-signal-panel">
              <header class="history-signal-head">
                <p class="history-signal-title">相关研究动态</p>
                <p class="history-signal-subtitle mono">
                  {{ historySignalPaperId || '-' }}
                </p>
              </header>
              <p v-if="historySignalLoading" class="muted history-signal-empty">正在加载相关动态...</p>
              <p v-else-if="historySignalErrorMessage" class="muted history-signal-error">{{ historySignalErrorMessage }}</p>
              <p v-else-if="!historySignalEvents.length" class="muted history-signal-empty">暂无与当前论文相关的动态。</p>
              <div v-else class="history-signal-list">
                <article v-for="event in historySignalEvents" :key="event.event_id" class="history-signal-card">
                  <p class="history-signal-card-title">{{ event.title }}</p>
                  <p class="history-signal-card-content">{{ event.content }}</p>
                  <p class="history-signal-card-meta mono">
                    {{ formatSignalEventType(event.event_type) }} · {{ formatDateTime(event.created_at) }}
                  </p>
                </article>
              </div>
            </section>
            <div class="history-detail-stage">
              <BloodLineageTree
                v-if="activeDetailTab === 'lineage' && historyLineageData"
                ref="historyLineageViewRef"
                :lineage="historyLineageData"
                :stretch-timeline="true"
              />
              <KnowledgeGraphCanvas v-else-if="domainGraphData" :graph="domainGraphData" :show-tools="true" />
              <KnowledgeGraphView
                v-else
                ref="historyGraphViewRef"
                :graph-data="selectedDetail.graph"
                mode="panorama_only"
              />
            </div>
          </div>
        </article>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import AppHeader from '../components/layout/AppHeader.vue';
import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import BloodLineageTree from '../components/lineage/BloodLineageTree.vue';
import KnowledgeGraphCanvas from '../components/graph/KnowledgeGraphCanvas.vue';
import KnowledgeGraphView from '../components/graph/KnowledgeGraphView.vue';
import { adaptDomainGraphFromHistoryGraph } from '../components/history/historyGraphAdapter';
import LoadingState from '../components/common/LoadingState.vue';
import { useGlobalConfirmDialog } from '../composables/useGlobalConfirmDialog';
import { getPaperSignalEvents } from '../api';
import { useAuthStore } from '../stores/authStore';
import { useResearchHistoryStore } from '../stores/researchHistoryStore';

const router = useRouter();
const { accessToken, isAuthenticated, loadSession } = useAuthStore();
const { askForConfirm } = useGlobalConfirmDialog();
const {
  records,
  selectedDetail,
  listLoading,
  detailLoading,
  deletingHistoryId,
  batchDeleting,
  errorMessage,
  page,
  pageSize,
  total,
  totalPages,
  hasRecords,
  fetchHistoryList,
  fetchHistoryDetail,
  deleteHistoryRecord,
  batchDeleteHistoryRecords,
  clearSelectedDetail
} = useResearchHistoryStore();

const activeDetailTab = ref('graph');
const historyGraphViewRef = ref(null);
const historyLineageViewRef = ref(null);
const selectedHistoryIds = ref([]);
const batchSelectMode = ref(false);
const historySignalEvents = ref([]);
const historySignalLoading = ref(false);
const historySignalErrorMessage = ref('');
const historySignalPaperId = ref('');
const activeHistoryId = computed(() => String(selectedDetail.value?.history_id || '').trim());
const selectedHistoryIdSet = computed(() => new Set(selectedHistoryIds.value));
const selectedCount = computed(() => selectedHistoryIds.value.length);
const currentPageHistoryIds = computed(() => {
  return records.value
    .map((item) => String(item?.history_id || '').trim())
    .filter(Boolean);
});
const domainGraphData = computed(() => {
  const detail = selectedDetail.value;
  if (!detail || String(detail.research_type || '').toLowerCase() !== 'domain') {
    return null;
  }

  if (Array.isArray(detail?.landscape_graph?.nodes) && Array.isArray(detail?.landscape_graph?.edges)) {
    return detail.landscape_graph;
  }

  return adaptDomainGraphFromHistoryGraph(detail.graph, detail.search_record);
});
const historyLineageData = computed(() => {
  const raw = selectedDetail.value?.lineage_graph;
  if (!raw || typeof raw !== 'object') return null;
  const root = raw.root || raw.root_paper;
  if (!root || typeof root !== 'object') return null;
  return raw;
});
const showDetailTabs = computed(() => Boolean(historyLineageData.value));
const showSignalPanel = computed(() => {
  const researchType = String(selectedDetail.value?.research_type || '').trim().toLowerCase();
  if (!selectedDetail.value) return false;
  return researchType === 'arxiv_id' || researchType === 'doi';
});

function goHome() {
  router.push({ name: 'home' });
}

function mapResearchType(type) {
  const normalized = String(type || '').trim().toLowerCase();
  if (normalized === 'arxiv_id') return 'arXiv ID';
  if (normalized === 'doi') return 'DOI ID';
  if (normalized === 'domain') return '领域研究';
  return '未知类型';
}

function formatDateTime(rawValue) {
  const date = new Date(rawValue);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function isSelected(historyId) {
  const safeHistoryId = String(historyId || '').trim();
  if (!safeHistoryId) return false;
  return selectedHistoryIdSet.value.has(safeHistoryId);
}

function toggleRowSelection(historyId, checked) {
  const safeHistoryId = String(historyId || '').trim();
  if (!safeHistoryId) return;

  const nextSet = new Set(selectedHistoryIds.value);
  if (checked) {
    nextSet.add(safeHistoryId);
  } else {
    nextSet.delete(safeHistoryId);
  }
  selectedHistoryIds.value = Array.from(nextSet);
}

function enableBatchSelectMode(checked) {
  if (!checked) return;
  batchSelectMode.value = true;
  selectedHistoryIds.value = [...currentPageHistoryIds.value];
}

function cancelBatchSelectMode() {
  batchSelectMode.value = false;
  selectedHistoryIds.value = [];
}

function syncSelectionWithCurrentPage() {
  const visibleSet = new Set(currentPageHistoryIds.value);
  selectedHistoryIds.value = selectedHistoryIds.value.filter((historyId) => visibleSet.has(historyId));
}

async function openDetail(historyId) {
  await fetchHistoryDetail(historyId, { accessToken: accessToken.value });
  await autoCenterPaperHistoryGraph();
  await autoCenterPaperHistoryLineage();
}

async function reloadHistoryAfterDelete({ deletedIds = [] } = {}) {
  const deletedSet = new Set(
    (Array.isArray(deletedIds) ? deletedIds : [])
      .map((historyId) => String(historyId || '').trim())
      .filter(Boolean)
  );
  const shouldReloadActive = deletedSet.has(activeHistoryId.value);

  await fetchHistoryList({ accessToken: accessToken.value, nextPage: page.value, nextPageSize: pageSize.value });
  if (!records.value.length && page.value > 1) {
    await fetchHistoryList({ accessToken: accessToken.value, nextPage: page.value - 1, nextPageSize: pageSize.value });
  }

  syncSelectionWithCurrentPage();

  if (!records.value.length) {
    clearSelectedDetail();
    return;
  }

  const hasActive = records.value.some((item) => item.history_id === activeHistoryId.value);
  if (shouldReloadActive || !hasActive) {
    await openDetail(records.value[0].history_id);
  }
}

async function deleteRecord(historyId) {
  const safeHistoryId = String(historyId || '').trim();
  if (!safeHistoryId) return;
  const target = records.value.find((item) => item.history_id === safeHistoryId);
  const targetLabel = String(target?.search_record || '该记录').trim() || '该记录';
  const confirmed = await askForConfirm({
    title: '删除研究历史',
    message: `确定删除「${targetLabel}」吗？删除后不可恢复。`,
    confirmText: '删除',
    cancelText: '取消',
    danger: true
  });
  if (!confirmed) return;

  const deleted = await deleteHistoryRecord(safeHistoryId, { accessToken: accessToken.value });
  if (!deleted) return;
  selectedHistoryIds.value = selectedHistoryIds.value.filter((id) => id !== safeHistoryId);
  await reloadHistoryAfterDelete({ deletedIds: [safeHistoryId] });
}

async function deleteSelectedRecords() {
  if (!batchSelectMode.value) return;
  const targetIds = [...selectedHistoryIds.value];
  if (!targetIds.length) return;

  const confirmed = await askForConfirm({
    title: '批量删除研究历史',
    message: `确定批量删除已选中的 ${targetIds.length} 条记录吗？删除后不可恢复。`,
    confirmText: '删除所选',
    cancelText: '取消',
    danger: true
  });
  if (!confirmed) return;

  const deletedIds = await batchDeleteHistoryRecords(targetIds, { accessToken: accessToken.value });
  if (!deletedIds.length) return;

  const deletedIdSet = new Set(deletedIds);
  selectedHistoryIds.value = selectedHistoryIds.value.filter((historyId) => !deletedIdSet.has(historyId));
  await reloadHistoryAfterDelete({ deletedIds });
  cancelBatchSelectMode();
}

async function changePage(nextPage) {
  await fetchHistoryList({ accessToken: accessToken.value, nextPage });
  syncSelectionWithCurrentPage();
  clearSelectedDetail();
  if (records.value.length > 0) {
    await openDetail(records.value[0].history_id);
  }
}

async function autoCenterPaperHistoryGraph() {
  const detail = selectedDetail.value;
  if (!detail) return;
  const researchType = String(detail.research_type || '').trim().toLowerCase();
  if (researchType === 'domain') return;
  if (activeDetailTab.value !== 'graph') return;
  await nextTick();
  await nextTick();
  if (!historyGraphViewRef.value?.refreshGraphDisplay) return;
  await historyGraphViewRef.value.refreshGraphDisplay();
}

async function autoCenterPaperHistoryLineage() {
  const detail = selectedDetail.value;
  if (!detail || !historyLineageData.value) return;
  if (activeDetailTab.value !== 'lineage') return;
  await nextTick();
  await nextTick();
  if (historyLineageViewRef.value?.refreshLineageToMinOverview) {
    await historyLineageViewRef.value.refreshLineageToMinOverview();
    return;
  }
  await historyLineageViewRef.value?.refreshLineageDisplay?.();
}

function formatSignalEventType(eventType) {
  const normalized = String(eventType || '').trim().toLowerCase();
  if (normalized === 'lineage_expanded') return '血缘扩展';
  if (normalized === 'controversy_rise') return '争议上升';
  if (normalized === 'citation_delta') return '引用变化';
  if (normalized === 'metadata_enriched') return '信息补全';
  return '研究动态';
}

function resolveSignalPaperIdFromDetail(detail) {
  if (!detail || typeof detail !== 'object') return '';
  const searchRecord = String(detail.search_record || '').trim();
  const lineageSeedPaperId = String(detail?.lineage?.seed_paper_id || '').trim();
  const lineageRootPaperId = String(detail?.lineage_graph?.root?.paper_id || detail?.lineage_graph?.root?.id || '').trim();
  return lineageSeedPaperId || lineageRootPaperId || searchRecord;
}

async function loadHistorySignalEvents() {
  historySignalEvents.value = [];
  historySignalErrorMessage.value = '';
  historySignalPaperId.value = '';

  if (!showSignalPanel.value) return;
  const paperId = resolveSignalPaperIdFromDetail(selectedDetail.value);
  historySignalPaperId.value = paperId;
  if (!paperId) return;

  historySignalLoading.value = true;
  try {
    const payload = await getPaperSignalEvents(
      {
        page: 1,
        pageSize: 4,
        unreadOnly: false,
        paperId
      },
      {
        accessToken: accessToken.value
      }
    );
    historySignalEvents.value = Array.isArray(payload?.items) ? payload.items : [];
  } catch (error) {
    historySignalEvents.value = [];
    historySignalErrorMessage.value = error?.message || '加载相关动态失败。';
  } finally {
    historySignalLoading.value = false;
  }
}

onMounted(async () => {
  await loadSession();
  if (!isAuthenticated.value) {
    router.replace({ name: 'home' });
    return;
  }
  await fetchHistoryList({ accessToken: accessToken.value, nextPage: 1 });
  if (records.value.length > 0) {
    await openDetail(records.value[0].history_id);
  }
  syncSelectionWithCurrentPage();
});

watch(
  () => selectedDetail.value?.history_id,
  async () => {
    activeDetailTab.value = 'graph';
    await loadHistorySignalEvents();
    await autoCenterPaperHistoryGraph();
    await autoCenterPaperHistoryLineage();
  }
);

watch(
  () => records.value,
  () => {
    syncSelectionWithCurrentPage();
    if (records.value.length === 0) {
      cancelBatchSelectMode();
    }
  }
);

watch(
  () => activeDetailTab.value,
  async (nextTab) => {
    if (nextTab === 'graph') {
      await autoCenterPaperHistoryGraph();
      return;
    }
    if (nextTab === 'lineage') {
      await autoCenterPaperHistoryLineage();
    }
  }
);
</script>
