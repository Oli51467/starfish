import { computed, ref } from 'vue';

import {
  createSavedPaperNote,
  createCollection,
  enrichSavedPaperMetadata as requestEnrichSavedPaperMetadata,
  getSavedPaperNotes as requestSavedPaperNotes,
  getCollections,
  getSavedPapers,
  removeSavedPaperNote,
  removeSavedPaper,
  savePaper,
  updateSavedPaperStatus
} from '../api';

const collections = ref([]);
const collectionsLoading = ref(false);
const collectionsErrorMessage = ref('');

const savedPapers = ref([]);
const savedPapersLoading = ref(false);
const savedPapersErrorMessage = ref('');
const savedPapersPage = ref(1);
const savedPapersPageSize = ref(20);
const savedPapersTotal = ref(0);
const savedPapersTotalPages = ref(0);

const savedPaperByPaperId = ref({});
const savedPaperBySavedId = ref({});
const bookmarkIndexLoading = ref(false);
const bookmarkIndexLoaded = ref(false);
const syncingPaperIdSet = ref(new Set());
const notesBySavedPaperId = ref({});
const notesLoadingBySavedPaperId = ref({});

const hasCollections = computed(() => collections.value.length > 0);
const hasSavedPapers = computed(() => savedPapers.value.length > 0);
const savedPaperIndexItems = computed(() => Object.values(savedPaperBySavedId.value));
const syncingPaperIds = computed(() => syncingPaperIdSet.value);
const unreadCount = computed(() => {
  return savedPapers.value.filter((item) => String(item?.read_status || '') === 'unread').length;
});
const readingCount = computed(() => {
  return savedPapers.value.filter((item) => String(item?.read_status || '') === 'reading').length;
});
const completedCount = computed(() => {
  return savedPapers.value.filter((item) => String(item?.read_status || '') === 'completed').length;
});
const unclassifiedCount = computed(() => {
  return savedPapers.value.filter((item) => !Array.isArray(item?.collection_ids) || item.collection_ids.length === 0).length;
});

function normalizeSavedPaperItem(rawItem) {
  const metadata = rawItem?.metadata && typeof rawItem.metadata === 'object'
    ? rawItem.metadata
    : {};
  const rawFields = Array.isArray(metadata?.fields_of_study)
    ? metadata.fields_of_study
    : Array.isArray(metadata?.fieldsOfStudy)
      ? metadata.fieldsOfStudy
      : String(metadata?.fields_of_study || metadata?.fieldsOfStudy || '')
        .split(/[;,，\n]+/g);
  return {
    saved_paper_id: String(rawItem?.saved_paper_id || '').trim(),
    paper_id: String(rawItem?.paper_id || '').trim(),
    read_status: String(rawItem?.read_status || 'unread').trim().toLowerCase(),
    saved_at: rawItem?.saved_at || null,
    last_opened_at: rawItem?.last_opened_at || null,
    collection_ids: Array.isArray(rawItem?.collection_ids)
      ? rawItem.collection_ids.map((item) => String(item || '').trim()).filter(Boolean)
      : [],
    metadata: {
      title: String(metadata?.title || '').trim(),
      abstract: String(metadata?.abstract || '').trim(),
      authors: Array.isArray(metadata?.authors)
        ? metadata.authors.map((item) => String(item || '').trim()).filter(Boolean)
        : [],
      year: Number.isFinite(Number(metadata?.year)) ? Number(metadata.year) : null,
      publication_date: String(metadata?.publication_date || metadata?.publicationDate || '').trim(),
      citation_count: Number.isFinite(Number(metadata?.citation_count)) ? Math.max(0, Number(metadata.citation_count)) : 0,
      impact_factor: Number.isFinite(Number(metadata?.impact_factor ?? metadata?.impactFactor))
        ? Math.max(0, Number(metadata?.impact_factor ?? metadata?.impactFactor))
        : null,
      fields_of_study: rawFields.map((item) => String(item || '').trim()).filter(Boolean),
      venue: String(metadata?.venue || '').trim(),
      url: String(metadata?.url || '').trim() || ''
    }
  };
}

function normalizeSavedPaperNote(rawItem) {
  return {
    note_id: String(rawItem?.note_id || rawItem?.id || '').trim(),
    saved_paper_id: String(rawItem?.saved_paper_id || '').trim(),
    content: String(rawItem?.content || '').trim(),
    created_at: rawItem?.created_at || null,
    updated_at: rawItem?.updated_at || null
  };
}

function replaceSavedPaperList(nextItems) {
  const normalized = Array.isArray(nextItems) ? nextItems.map(normalizeSavedPaperItem) : [];
  savedPapers.value = normalized;
}

function rebuildBookmarkIndex(items) {
  const byPaperId = {};
  const bySavedId = {};
  for (const item of Array.isArray(items) ? items : []) {
    const normalized = normalizeSavedPaperItem(item);
    if (normalized.paper_id) {
      byPaperId[normalized.paper_id] = normalized;
    }
    if (normalized.saved_paper_id) {
      bySavedId[normalized.saved_paper_id] = normalized;
    }
  }
  savedPaperByPaperId.value = byPaperId;
  savedPaperBySavedId.value = bySavedId;
}

function patchSavedPaperInLocalState(item) {
  const normalized = normalizeSavedPaperItem(item);
  if (!normalized.saved_paper_id || !normalized.paper_id) return;

  savedPaperByPaperId.value = {
    ...savedPaperByPaperId.value,
    [normalized.paper_id]: normalized
  };
  savedPaperBySavedId.value = {
    ...savedPaperBySavedId.value,
    [normalized.saved_paper_id]: normalized
  };

  const index = savedPapers.value.findIndex((current) => current.saved_paper_id === normalized.saved_paper_id);
  if (index >= 0) {
    const next = [...savedPapers.value];
    next.splice(index, 1, normalized);
    savedPapers.value = next;
  }
}

function removeSavedPaperInLocalState(savedPaperId) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  if (!safeSavedPaperId) return;
  const current = savedPaperBySavedId.value[safeSavedPaperId];
  const paperId = String(current?.paper_id || '').trim();

  if (paperId) {
    const nextByPaperId = { ...savedPaperByPaperId.value };
    delete nextByPaperId[paperId];
    savedPaperByPaperId.value = nextByPaperId;
  }
  const nextBySavedId = { ...savedPaperBySavedId.value };
  delete nextBySavedId[safeSavedPaperId];
  savedPaperBySavedId.value = nextBySavedId;

  savedPapers.value = savedPapers.value.filter((item) => item.saved_paper_id !== safeSavedPaperId);
}

function markPaperSyncing(paperId, syncing) {
  const safePaperId = String(paperId || '').trim();
  if (!safePaperId) return;
  const next = new Set(syncingPaperIdSet.value);
  if (syncing) {
    next.add(safePaperId);
  } else {
    next.delete(safePaperId);
  }
  syncingPaperIdSet.value = next;
}

function setSavedPaperNotes(savedPaperId, notes) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  if (!safeSavedPaperId) return;
  notesBySavedPaperId.value = {
    ...notesBySavedPaperId.value,
    [safeSavedPaperId]: Array.isArray(notes) ? notes.map(normalizeSavedPaperNote).filter((item) => item.note_id) : []
  };
}

function setSavedPaperNotesLoading(savedPaperId, loading) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  if (!safeSavedPaperId) return;
  notesLoadingBySavedPaperId.value = {
    ...notesLoadingBySavedPaperId.value,
    [safeSavedPaperId]: Boolean(loading)
  };
}

function getSavedPaperNotesBySavedId(savedPaperId) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  if (!safeSavedPaperId) return [];
  return Array.isArray(notesBySavedPaperId.value[safeSavedPaperId])
    ? notesBySavedPaperId.value[safeSavedPaperId]
    : [];
}

async function fetchSavedPaperNotes(savedPaperId, { accessToken = '', force = false, limit = 30 } = {}) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  if (!safeSavedPaperId) return [];
  if (!force && notesBySavedPaperId.value[safeSavedPaperId]) {
    return getSavedPaperNotesBySavedId(safeSavedPaperId);
  }
  setSavedPaperNotesLoading(safeSavedPaperId, true);
  try {
    const payload = await requestSavedPaperNotes(safeSavedPaperId, { accessToken, limit });
    const items = Array.isArray(payload?.items) ? payload.items.map(normalizeSavedPaperNote).filter((item) => item.note_id) : [];
    setSavedPaperNotes(safeSavedPaperId, items);
    return items;
  } catch (error) {
    savedPapersErrorMessage.value = error?.message || '加载笔记失败。';
    setSavedPaperNotes(safeSavedPaperId, []);
    return [];
  } finally {
    setSavedPaperNotesLoading(safeSavedPaperId, false);
  }
}

async function addSavedPaperNote(savedPaperId, content, { accessToken = '' } = {}) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  const safeContent = String(content || '').trim();
  if (!safeSavedPaperId || !safeContent) {
    throw new Error('saved_paper_note_required');
  }
  setSavedPaperNotesLoading(safeSavedPaperId, true);
  try {
    const created = await createSavedPaperNote(safeSavedPaperId, { content: safeContent }, { accessToken });
    const normalized = normalizeSavedPaperNote(created || {});
    const current = getSavedPaperNotesBySavedId(safeSavedPaperId);
    setSavedPaperNotes(safeSavedPaperId, [normalized, ...current]);
    return normalized;
  } finally {
    setSavedPaperNotesLoading(safeSavedPaperId, false);
  }
}

async function deleteSavedPaperNoteById(savedPaperId, noteId, { accessToken = '' } = {}) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  const safeNoteId = String(noteId || '').trim();
  if (!safeSavedPaperId || !safeNoteId) return false;
  setSavedPaperNotesLoading(safeSavedPaperId, true);
  try {
    const payload = await removeSavedPaperNote(safeSavedPaperId, safeNoteId, { accessToken });
    if (payload?.deleted) {
      const next = getSavedPaperNotesBySavedId(safeSavedPaperId).filter((item) => item.note_id !== safeNoteId);
      setSavedPaperNotes(safeSavedPaperId, next);
      return true;
    }
    return false;
  } finally {
    setSavedPaperNotesLoading(safeSavedPaperId, false);
  }
}

function isPaperSyncing(paperId) {
  const safePaperId = String(paperId || '').trim();
  return Boolean(safePaperId && syncingPaperIdSet.value.has(safePaperId));
}

function getSavedPaperByPaperId(paperId) {
  const safePaperId = String(paperId || '').trim();
  if (!safePaperId) return null;
  return savedPaperByPaperId.value[safePaperId] || null;
}

function isPaperSaved(paperId) {
  return Boolean(getSavedPaperByPaperId(paperId));
}

async function fetchCollections({ accessToken = '' } = {}) {
  collectionsLoading.value = true;
  collectionsErrorMessage.value = '';
  try {
    const payload = await getCollections({ accessToken });
    const items = Array.isArray(payload?.items) ? payload.items : [];
    collections.value = items.map((item) => ({
      collection_id: String(item?.collection_id || '').trim(),
      name: String(item?.name || '').trim(),
      color: String(item?.color || '').trim(),
      emoji: String(item?.emoji || '').trim(),
      paper_count: Number.isFinite(Number(item?.paper_count)) ? Math.max(0, Number(item.paper_count)) : 0
    })).filter((item) => item.collection_id);
    return collections.value;
  } catch (error) {
    collections.value = [];
    collectionsErrorMessage.value = error?.message || '获取收藏分组失败。';
    return [];
  } finally {
    collectionsLoading.value = false;
  }
}

async function querySavedPapers({
  accessToken = '',
  page = 1,
  pageSize = 20,
  collectionId = '',
  readStatus = '',
  keyword = '',
  sortBy = 'saved_at',
  sortOrder = 'desc'
} = {}) {
  savedPapersLoading.value = true;
  savedPapersErrorMessage.value = '';
  try {
    const payload = await getSavedPapers({
      accessToken,
      page,
      pageSize,
      collectionId,
      readStatus,
      keyword,
      sortBy,
      sortOrder
    });
    replaceSavedPaperList(payload?.items || []);
    savedPapersPage.value = Number(payload?.page || page) || 1;
    savedPapersPageSize.value = Number(payload?.page_size || pageSize) || 20;
    savedPapersTotal.value = Number(payload?.total || 0) || 0;
    savedPapersTotalPages.value = Number(payload?.total_pages || 0) || 0;

    for (const item of savedPapers.value) {
      patchSavedPaperInLocalState(item);
    }
    return savedPapers.value;
  } catch (error) {
    replaceSavedPaperList([]);
    savedPapersTotal.value = 0;
    savedPapersTotalPages.value = 0;
    savedPapersErrorMessage.value = error?.message || '获取收藏论文失败。';
    return [];
  } finally {
    savedPapersLoading.value = false;
  }
}

async function ensureBookmarkIndexLoaded({ accessToken = '', force = false } = {}) {
  if (!force && (bookmarkIndexLoaded.value || bookmarkIndexLoading.value)) {
    return;
  }
  bookmarkIndexLoading.value = true;
  try {
    const merged = [];
    let page = 1;
    let totalPages = 1;
    while (page <= totalPages && page <= 40) {
      const payload = await getSavedPapers({
        accessToken,
        page,
        pageSize: 50,
        sortBy: 'saved_at',
        sortOrder: 'desc'
      });
      const items = Array.isArray(payload?.items) ? payload.items.map(normalizeSavedPaperItem) : [];
      merged.push(...items);
      totalPages = Number(payload?.total_pages || 1) || 1;
      page += 1;
    }
    rebuildBookmarkIndex(merged);
    bookmarkIndexLoaded.value = true;
  } catch (error) {
    savedPapersErrorMessage.value = error?.message || '加载收藏状态失败。';
  } finally {
    bookmarkIndexLoading.value = false;
  }
}

async function togglePaperSaved({
  accessToken = '',
  paperId = '',
  metadata = null,
  collectionIds = []
} = {}) {
  const safePaperId = String(paperId || '').trim();
  if (!safePaperId) {
    throw new Error('paper_id_required');
  }

  const existing = getSavedPaperByPaperId(safePaperId);
  markPaperSyncing(safePaperId, true);
  try {
    if (existing?.saved_paper_id) {
      const payload = await removeSavedPaper(existing.saved_paper_id, { accessToken });
      if (!payload?.deleted) {
        throw new Error('saved_paper_delete_failed');
      }
      removeSavedPaperInLocalState(existing.saved_paper_id);
      return { saved: false, item: null };
    }

    const created = await savePaper({
      paper_id: safePaperId,
      collection_ids: Array.isArray(collectionIds) ? collectionIds : [],
      metadata: metadata && typeof metadata === 'object' ? metadata : undefined
    }, { accessToken });
    const normalized = normalizeSavedPaperItem(created || {});
    patchSavedPaperInLocalState(normalized);
    if (!savedPapers.value.find((item) => item.saved_paper_id === normalized.saved_paper_id)) {
      savedPapers.value = [normalized, ...savedPapers.value];
    }
    return { saved: true, item: normalized };
  } finally {
    markPaperSyncing(safePaperId, false);
  }
}

async function setSavedPaperReadStatus(savedPaperId, readStatus, { accessToken = '' } = {}) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  const safeReadStatus = String(readStatus || '').trim().toLowerCase();
  if (!safeSavedPaperId || !safeReadStatus) return null;

  const payload = await updateSavedPaperStatus(
    safeSavedPaperId,
    { read_status: safeReadStatus, touch_last_opened: true },
    { accessToken }
  );
  const normalized = normalizeSavedPaperItem(payload || {});
  patchSavedPaperInLocalState(normalized);
  return normalized;
}

async function enrichSavedPaperMetadata(savedPaperId, { accessToken = '', force = false, silent = true } = {}) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  if (!safeSavedPaperId) return null;
  try {
    const payload = await requestEnrichSavedPaperMetadata(
      safeSavedPaperId,
      { accessToken, force }
    );
    const normalized = normalizeSavedPaperItem(payload || {});
    patchSavedPaperInLocalState(normalized);
    return normalized;
  } catch (error) {
    if (!silent) {
      savedPapersErrorMessage.value = error?.message || '补全论文元数据失败。';
    }
    return null;
  }
}

async function createCollectionQuick(name, { accessToken = '' } = {}) {
  const safeName = String(name || '').trim();
  if (!safeName) {
    throw new Error('collection_name_required');
  }
  const created = await createCollection({ name: safeName }, { accessToken });
  await fetchCollections({ accessToken });
  return created;
}

function clearCollectionStoreState() {
  collections.value = [];
  savedPapers.value = [];
  savedPapersTotal.value = 0;
  savedPapersTotalPages.value = 0;
  savedPaperByPaperId.value = {};
  savedPaperBySavedId.value = {};
  bookmarkIndexLoaded.value = false;
  syncingPaperIdSet.value = new Set();
  notesBySavedPaperId.value = {};
  notesLoadingBySavedPaperId.value = {};
  collectionsErrorMessage.value = '';
  savedPapersErrorMessage.value = '';
}

export function useCollectionStore() {
  return {
    collections,
    collectionsLoading,
    collectionsErrorMessage,
    hasCollections,
    savedPapers,
    savedPapersLoading,
    savedPapersErrorMessage,
    savedPapersPage,
    savedPapersPageSize,
    savedPapersTotal,
    savedPapersTotalPages,
    hasSavedPapers,
    savedPaperIndexItems,
    unreadCount,
    readingCount,
    completedCount,
    unclassifiedCount,
    syncingPaperIds,
    bookmarkIndexLoading,
    notesBySavedPaperId,
    notesLoadingBySavedPaperId,
    fetchCollections,
    querySavedPapers,
    ensureBookmarkIndexLoaded,
    togglePaperSaved,
    setSavedPaperReadStatus,
    enrichSavedPaperMetadata,
    fetchSavedPaperNotes,
    getSavedPaperNotesBySavedId,
    addSavedPaperNote,
    deleteSavedPaperNoteById,
    createCollectionQuick,
    getSavedPaperByPaperId,
    isPaperSaved,
    isPaperSyncing,
    clearCollectionStoreState
  };
}
