import { ref } from 'vue';

import { getGaps, getLineage, getReadingList } from '../api';

const readingList = ref(null);
const gaps = ref(null);
const lineage = ref(null);

const readingListLoading = ref(false);
const gapsLoading = ref(false);
const lineageLoading = ref(false);

const readingListErrorMessage = ref('');
const gapsErrorMessage = ref('');
const lineageErrorMessage = ref('');

async function runRequest({
  requestFn,
  loadingRef,
  errorRef,
  fallbackMessage,
  onSuccess
}) {
  loadingRef.value = true;
  errorRef.value = '';
  try {
    const payload = await requestFn();
    onSuccess(payload);
    return payload;
  } catch (error) {
    errorRef.value = error.message || fallbackMessage;
    return null;
  } finally {
    loadingRef.value = false;
  }
}

async function loadReadingList(mapId, options = {}) {
  if (!mapId) return;
  return await runRequest({
    requestFn: () => getReadingList(mapId, options),
    loadingRef: readingListLoading,
    errorRef: readingListErrorMessage,
    fallbackMessage: '获取必读清单失败。',
    onSuccess: (payload) => {
      readingList.value = payload;
    }
  });
}

async function loadGaps(mapId, options = {}) {
  if (!mapId) return;
  return await runRequest({
    requestFn: () => getGaps(mapId, options),
    loadingRef: gapsLoading,
    errorRef: gapsErrorMessage,
    fallbackMessage: '获取研究空白失败。',
    onSuccess: (payload) => {
      gaps.value = payload;
    }
  });
}

async function loadLineage(paperId, options = {}) {
  if (!paperId) return;
  return await runRequest({
    requestFn: () => getLineage(paperId, options),
    loadingRef: lineageLoading,
    errorRef: lineageErrorMessage,
    fallbackMessage: '获取血缘树失败。',
    onSuccess: (payload) => {
      lineage.value = payload;
    }
  });
}

function clearLineage() {
  lineage.value = null;
  lineageErrorMessage.value = '';
}

export function usePaperStore() {
  return {
    readingList,
    gaps,
    lineage,
    readingListLoading,
    gapsLoading,
    lineageLoading,
    readingListErrorMessage,
    gapsErrorMessage,
    lineageErrorMessage,
    loadReadingList,
    loadGaps,
    loadLineage,
    clearLineage
  };
}
