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
                    <th>搜索范围</th>
                    <th>血缘树</th>
                    <th>搜索时间</th>
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
                    <td>{{ mapSearchRange(item.search_range, item.research_type) }}</td>
                    <td>
                      <span class="history-lineage-badge mono" :class="mapLineageStatusClass(item)">
                        {{ mapLineageStatusLabel(item) }}
                      </span>
                    </td>
                    <td>{{ formatDateTime(item.search_time) }}</td>
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
          <KnowledgeGraphCanvas v-else-if="domainGraphData" :graph="domainGraphData" :show-tools="true" />
          <KnowledgeGraphView v-else :graph-data="selectedDetail.graph" mode="panorama_only" />
        </article>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';

import AppHeader from '../components/layout/AppHeader.vue';
import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import KnowledgeGraphCanvas from '../components/graph/KnowledgeGraphCanvas.vue';
import KnowledgeGraphView from '../components/graph/KnowledgeGraphView.vue';
import { adaptDomainGraphFromHistoryGraph } from '../components/history/historyGraphAdapter';
import LoadingState from '../components/common/LoadingState.vue';
import { useAuthStore } from '../stores/authStore';
import { useResearchHistoryStore } from '../stores/researchHistoryStore';

const router = useRouter();
const { accessToken, isAuthenticated, loadSession } = useAuthStore();
const {
  records,
  selectedDetail,
  listLoading,
  detailLoading,
  errorMessage,
  page,
  total,
  totalPages,
  hasRecords,
  fetchHistoryList,
  fetchHistoryDetail,
  clearSelectedDetail
} = useResearchHistoryStore();

const activeHistoryId = computed(() => String(selectedDetail.value?.history_id || '').trim());
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

function mapSearchRange(searchRange, researchType) {
  const value = String(searchRange || '').trim();
  if (value) return value;
  return String(researchType || '').toLowerCase() === 'domain' ? '所有时间' : '不适用';
}

function mapLineageStatusLabel(item) {
  const researchType = String(item?.research_type || '').trim().toLowerCase();
  if (researchType === 'domain') return '不适用';
  const lineage = item?.lineage || {};
  if (!lineage?.generated) return '未生成';
  const ancestors = Number(lineage?.ancestor_count || 0);
  const descendants = Number(lineage?.descendant_count || 0);
  return `已生成 ${Math.max(0, Math.round(ancestors))}/${Math.max(0, Math.round(descendants))}`;
}

function mapLineageStatusClass(item) {
  const researchType = String(item?.research_type || '').trim().toLowerCase();
  if (researchType === 'domain') return 'is-na';
  return item?.lineage?.generated ? 'is-done' : 'is-pending';
}

function formatDateTime(rawValue) {
  const date = new Date(rawValue);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', { hour12: false });
}

async function openDetail(historyId) {
  await fetchHistoryDetail(historyId, { accessToken: accessToken.value });
}

async function changePage(nextPage) {
  await fetchHistoryList({ accessToken: accessToken.value, nextPage });
  clearSelectedDetail();
  if (records.value.length > 0) {
    await openDetail(records.value[0].history_id);
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
});
</script>
