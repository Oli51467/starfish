import { ref } from 'vue';

import { getGaps, getLineage, getReadingList } from '../api';

const readingList = ref(null);
const gaps = ref(null);
const lineage = ref(null);
const loading = ref(false);
const errorMessage = ref('');

async function loadReadingList(mapId, options = {}) {
  if (!mapId) return;
  loading.value = true;
  errorMessage.value = '';
  try {
    readingList.value = await getReadingList(mapId, options);
  } catch (error) {
    errorMessage.value = error.message || '获取必读清单失败。';
  } finally {
    loading.value = false;
  }
}

async function loadGaps(mapId, options = {}) {
  if (!mapId) return;
  loading.value = true;
  errorMessage.value = '';
  try {
    gaps.value = await getGaps(mapId, options);
  } catch (error) {
    errorMessage.value = error.message || '获取研究空白失败。';
  } finally {
    loading.value = false;
  }
}

async function loadLineage(paperId, options = {}) {
  if (!paperId) return;
  loading.value = true;
  errorMessage.value = '';
  try {
    lineage.value = await getLineage(paperId, options);
  } catch (error) {
    errorMessage.value = error.message || '获取论文血缘树失败。';
  } finally {
    loading.value = false;
  }
}

export function usePaperStore() {
  return {
    readingList,
    gaps,
    lineage,
    loading,
    errorMessage,
    loadReadingList,
    loadGaps,
    loadLineage
  };
}
