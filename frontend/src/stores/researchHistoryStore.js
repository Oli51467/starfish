import { computed, ref } from 'vue';

import { getResearchHistoryDetail, getResearchHistoryList } from '../api';

const records = ref([]);
const selectedDetail = ref(null);
const listLoading = ref(false);
const detailLoading = ref(false);
const errorMessage = ref('');
const page = ref(1);
const pageSize = ref(10);
const total = ref(0);
const totalPages = ref(0);

const hasRecords = computed(() => records.value.length > 0);

async function fetchHistoryList({ accessToken, nextPage = page.value, nextPageSize = pageSize.value } = {}) {
  listLoading.value = true;
  errorMessage.value = '';
  try {
    const payload = await getResearchHistoryList({
      page: nextPage,
      pageSize: nextPageSize,
      accessToken
    });
    records.value = Array.isArray(payload?.items) ? payload.items : [];
    page.value = Number(payload?.page || nextPage) || 1;
    pageSize.value = Number(payload?.page_size || nextPageSize) || 10;
    total.value = Number(payload?.total || 0) || 0;
    totalPages.value = Number(payload?.total_pages || 0) || 0;
  } catch (error) {
    records.value = [];
    total.value = 0;
    totalPages.value = 0;
    errorMessage.value = error?.message || '获取研究历史失败。';
  } finally {
    listLoading.value = false;
  }
}

async function fetchHistoryDetail(historyId, { accessToken } = {}) {
  const safeHistoryId = String(historyId || '').trim();
  if (!safeHistoryId) return;

  detailLoading.value = true;
  errorMessage.value = '';
  try {
    const payload = await getResearchHistoryDetail(safeHistoryId, { accessToken });
    selectedDetail.value = payload || null;
  } catch (error) {
    selectedDetail.value = null;
    errorMessage.value = error?.message || '获取历史详情失败。';
  } finally {
    detailLoading.value = false;
  }
}

function clearSelectedDetail() {
  selectedDetail.value = null;
}

export function useResearchHistoryStore() {
  return {
    records,
    selectedDetail,
    listLoading,
    detailLoading,
    errorMessage,
    page,
    pageSize,
    total,
    totalPages,
    hasRecords,
    fetchHistoryList,
    fetchHistoryDetail,
    clearSelectedDetail
  };
}
