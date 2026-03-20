<template>
  <div class="app">
    <AppHeader :show-back="true" @back="goHome" />

    <main class="workspace workspace-workflow">
      <section class="collection-layout">
        <aside class="panel collection-sidebar">
          <div class="panel-head">
            <h2>我的论文</h2>
            <button
              class="btn collection-create-btn"
              type="button"
              aria-label="新建分组"
              title="新建分组"
              @click="promptCreateCollection"
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="M8 3.2v9.6M3.2 8h9.6" />
              </svg>
            </button>
          </div>
          <div class="panel-body">
            <div class="collection-nav">
              <button
                class="collection-nav-item mono"
                :class="{ 'is-active': activeCollectionId === '' }"
                type="button"
                @click="setActiveCollection('')"
              >
                全部论文
                <span>{{ savedPapersTotal }}</span>
              </button>
              <button
                class="collection-nav-item mono"
                :class="{ 'is-active': activeCollectionId === UNCLASSIFIED_COLLECTION_ID }"
                type="button"
                @click="setActiveCollection(UNCLASSIFIED_COLLECTION_ID)"
              >
                未分类
                <span>{{ unclassifiedCount }}</span>
              </button>
            </div>

            <LoadingState v-if="collectionsLoading" message="正在加载分组..." />
            <ErrorBoundary v-else-if="collectionsErrorMessage" :message="collectionsErrorMessage" />
            <div v-else-if="collections.length" class="collection-nav">
              <button
                v-for="item in collections"
                :key="item.collection_id"
                class="collection-nav-item"
                :class="{ 'is-active': activeCollectionId === item.collection_id }"
                type="button"
                @click="setActiveCollection(item.collection_id)"
              >
                <span class="collection-name-wrap">
                  <span class="collection-emoji" aria-hidden="true">{{ item.emoji || '📁' }}</span>
                  <span class="collection-name">{{ item.name }}</span>
                </span>
                <span>{{ item.paper_count }}</span>
              </button>
            </div>
          </div>
        </aside>

        <article class="panel collection-main">
          <div class="panel-head collection-main-head">
            <h2>{{ activeCollectionTitle }}</h2>
            <div class="collection-status-summary mono">
              未读 {{ unreadCount }} · 阅读中 {{ readingCount }} · 已读 {{ completedCount }}
            </div>
          </div>
          <div class="panel-body collection-main-body">
            <div class="collection-filter-row">
              <input
                v-model.trim="keyword"
                class="text-input mono collection-filter-input"
                type="text"
                placeholder="搜索标题 / 论文 ID"
                @keydown.enter.prevent="reloadSavedPapers"
              />
              <select v-model="readStatusFilter" class="text-input mono collection-filter-select">
                <option value="">全部状态</option>
                <option value="unread">未读</option>
                <option value="reading">阅读中</option>
                <option value="completed">已读</option>
              </select>
              <select v-model="sortBy" class="text-input mono collection-filter-select">
                <option value="saved_at">收藏时间</option>
                <option value="last_opened_at">最近打开</option>
                <option value="year">发表年份</option>
                <option value="citation_count">引用数</option>
              </select>
              <button class="btn mono collection-query-btn" type="button" @click="reloadSavedPapers">查询</button>
            </div>

            <LoadingState v-if="savedPapersLoading" message="正在加载论文..." />
            <ErrorBoundary v-else-if="savedPapersErrorMessage && !savedPapers.length" :message="savedPapersErrorMessage" />
            <p v-else-if="!visiblePapers.length" class="muted">当前筛选条件下暂无论文。</p>
            <div v-else class="collection-paper-list">
              <article
                v-for="item in visiblePapers"
                :key="item.saved_paper_id"
                class="collection-paper-card"
                :class="{ 'is-read': isRead(item.read_status) }"
              >
                <div class="collection-card-grid">
                  <section class="collection-info-area">
                    <p class="collection-paper-title">{{ item.metadata.title || item.paper_id }}</p>
                    <div class="collection-meta-grid">
                      <div class="collection-meta-item">
                        <span class="collection-meta-label mono">收藏时间</span>
                        <span class="collection-meta-value mono">{{ formatDateTime(item.saved_at) }}</span>
                      </div>
                      <div class="collection-meta-item">
                        <span class="collection-meta-label mono">论文作者</span>
                        <span class="collection-meta-value">{{ formatAuthors(item.metadata.authors) }}</span>
                      </div>
                      <div class="collection-meta-item">
                        <span class="collection-meta-label mono">发表时间</span>
                        <span class="collection-meta-value mono">{{ formatPublicationTime(item.metadata.publication_date, item.metadata.year) }}</span>
                      </div>
                      <div class="collection-meta-item">
                        <span class="collection-meta-label mono">影响因子</span>
                        <span class="collection-meta-value mono accent">{{ formatImpactFactor(item.metadata.impact_factor) }}</span>
                      </div>
                      <div class="collection-meta-item">
                        <span class="collection-meta-label mono">引用数</span>
                        <span class="collection-meta-value mono">{{ Number(item.metadata.citation_count || 0).toLocaleString() }}</span>
                      </div>
                      <div class="collection-meta-item">
                        <span class="collection-meta-label mono">论文领域</span>
                        <span class="collection-meta-value tag">{{ formatFields(item.metadata.fields_of_study) }}</span>
                      </div>
                    </div>
                    <div v-if="shouldShowAbstract(item.metadata.abstract)" class="collection-abstract-block">
                      <p class="collection-paper-abstract">
                        {{ formatAbstract(item.metadata.abstract) }}
                      </p>
                    </div>
                  </section>

                  <aside class="collection-actions-area">
                    <button
                      class="collection-icon-btn collection-note-add-btn"
                      :class="{ active: isNoteEditorOpen(item.saved_paper_id) }"
                      type="button"
                      :title="isNoteEditorOpen(item.saved_paper_id) ? '收起笔记' : '新增笔记'"
                      :aria-label="isNoteEditorOpen(item.saved_paper_id) ? '收起笔记' : '新增笔记'"
                      @click="toggleNoteEditor(item)"
                    >
                      <svg viewBox="0 0 16 16" aria-hidden="true">
                        <path d="M8 3.2v9.6M3.2 8h9.6" />
                      </svg>
                    </button>
                    <button
                      class="collection-icon-btn collection-read-btn"
                      :class="{ 'is-read': isRead(item.read_status) }"
                      type="button"
                      :title="isRead(item.read_status) ? '标记未读' : '标记已读'"
                      :aria-label="isRead(item.read_status) ? '标记未读' : '标记已读'"
                      @click="toggleReadStatus(item)"
                    >
                      <svg v-if="isRead(item.read_status)" viewBox="0 0 16 16" aria-hidden="true">
                        <path d="M3.5 8.2l2.8 2.8 6.2-6.2" />
                      </svg>
                      <svg v-else viewBox="0 0 16 16" aria-hidden="true">
                        <circle cx="8" cy="8" r="4.5" />
                      </svg>
                    </button>
                    <button
                      class="collection-icon-btn collection-star-btn is-saved"
                      type="button"
                      title="取消收藏"
                      aria-label="取消收藏"
                      @click="removePaper(item)"
                    >
                      <svg viewBox="0 0 16 16" aria-hidden="true">
                        <path d="M8 1.3l1.96 3.97 4.38.64-3.17 3.09.75 4.36L8 11.28l-3.92 2.08.75-4.36L1.66 5.91l4.38-.64L8 1.3z" />
                      </svg>
                    </button>
                  </aside>

                  <transition name="collection-note-slide">
                    <section
                      v-if="isNotePanelVisible(item)"
                      class="collection-paper-notes"
                    >
                      <div class="collection-note-head">
                        <p class="collection-note-title mono">笔记</p>
                        <span v-if="notesLoadingBySavedPaperId[item.saved_paper_id]" class="collection-note-sync mono">
                          <span class="collection-note-sync-dot"></span>同步中…
                        </span>
                      </div>
                      <div v-if="isNoteEditorOpen(item.saved_paper_id)" class="collection-note-editor">
                        <input
                          v-model.trim="noteDraftMap[item.saved_paper_id]"
                          class="text-input mono collection-note-input"
                          type="text"
                          placeholder="输入笔记，回车保存…"
                          @keydown.enter.prevent="submitNote(item)"
                        />
                      </div>
                      <div v-if="notesForPaper(item.saved_paper_id).length" class="collection-note-list">
                        <article
                          v-for="note in notesForPaper(item.saved_paper_id)"
                          :key="note.note_id"
                          class="collection-note-card"
                        >
                          <p class="collection-note-content">{{ note.content }}</p>
                          <button
                            class="collection-note-remove"
                            type="button"
                            aria-label="删除笔记"
                            title="删除笔记"
                            @click="removeNote(item, note)"
                          >
                            <svg viewBox="0 0 16 16" aria-hidden="true">
                              <path d="M4 4l8 8M12 4l-8 8" />
                            </svg>
                          </button>
                        </article>
                      </div>
                    </section>
                  </transition>
                </div>
              </article>
            </div>

            <div v-if="showPagination" class="collection-pagination">
              <button class="btn mono" type="button" :disabled="savedPapersPage <= 1" @click="changePage(savedPapersPage - 1)">
                上一页
              </button>
              <span class="mono">{{ savedPapersPage }} / {{ savedPapersTotalPages }}</span>
              <button
                class="btn mono"
                type="button"
                :disabled="savedPapersPage >= savedPapersTotalPages"
                @click="changePage(savedPapersPage + 1)"
              >
                下一页
              </button>
            </div>
          </div>
        </article>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import AppHeader from '../components/layout/AppHeader.vue';
import ErrorBoundary from '../components/common/ErrorBoundary.vue';
import LoadingState from '../components/common/LoadingState.vue';
import { useAuthStore } from '../stores/authStore';
import { useCollectionStore } from '../stores/collectionStore';

const UNCLASSIFIED_COLLECTION_ID = '__unclassified__';

const router = useRouter();
const { accessToken, isAuthenticated, loadSession } = useAuthStore();
const {
  collections,
  collectionsLoading,
  collectionsErrorMessage,
  savedPapers,
  savedPapersLoading,
  savedPapersErrorMessage,
  savedPapersPage,
  savedPapersPageSize,
  savedPapersTotal,
  savedPapersTotalPages,
  unreadCount,
  readingCount,
  completedCount,
  unclassifiedCount,
  savedPaperIndexItems,
  notesBySavedPaperId,
  notesLoadingBySavedPaperId,
  fetchCollections,
  querySavedPapers,
  setSavedPaperReadStatus,
  fetchSavedPaperNotes,
  addSavedPaperNote,
  deleteSavedPaperNoteById,
  createCollectionQuick,
  togglePaperSaved,
  ensureBookmarkIndexLoaded,
  enrichSavedPaperMetadata
} = useCollectionStore();

const activeCollectionId = ref('');
const readStatusFilter = ref('');
const keyword = ref('');
const sortBy = ref('saved_at');
const sortOrder = ref('desc');
const noteDraftMap = ref({});
const noteEditorOpenMap = ref({});
const metadataEnrichAttemptedSet = ref(new Set());

const collectionNameMap = computed(() => {
  const mapped = {};
  for (const item of collections.value) {
    mapped[item.collection_id] = item.name;
  }
  return mapped;
});

const activeCollectionTitle = computed(() => {
  const target = String(activeCollectionId.value || '').trim();
  if (!target) return '全部论文';
  if (target === UNCLASSIFIED_COLLECTION_ID) return '未分类';
  return collectionNameMap.value[target] || '论文分组';
});

const showPagination = computed(() => {
  if (activeCollectionId.value === UNCLASSIFIED_COLLECTION_ID) return false;
  return savedPapersTotalPages.value > 1;
});

const visiblePapers = computed(() => {
  if (activeCollectionId.value !== UNCLASSIFIED_COLLECTION_ID) {
    return savedPapers.value;
  }
  const keywordText = String(keyword.value || '').trim().toLowerCase();
  const status = String(readStatusFilter.value || '').trim().toLowerCase();
  const sorted = [...savedPaperIndexItems.value]
    .filter((item) => !item.collection_ids.length)
    .filter((item) => (status ? String(item.read_status || '') === status : true))
    .filter((item) => {
      if (!keywordText) return true;
      const titleText = String(item?.metadata?.title || '').toLowerCase();
      const paperIdText = String(item?.paper_id || '').toLowerCase();
      return titleText.includes(keywordText) || paperIdText.includes(keywordText);
    });
  if (sortBy.value === 'year') {
    sorted.sort((left, right) => Number(right?.metadata?.year || 0) - Number(left?.metadata?.year || 0));
  } else if (sortBy.value === 'citation_count') {
    sorted.sort((left, right) => Number(right?.metadata?.citation_count || 0) - Number(left?.metadata?.citation_count || 0));
  } else if (sortBy.value === 'last_opened_at') {
    sorted.sort((left, right) => String(right?.last_opened_at || '').localeCompare(String(left?.last_opened_at || '')));
  } else {
    sorted.sort((left, right) => String(right?.saved_at || '').localeCompare(String(left?.saved_at || '')));
  }
  if (sortOrder.value === 'asc') {
    sorted.reverse();
  }
  return sorted;
});

function goHome() {
  router.push({ name: 'home' });
}

async function reloadSavedPapers({ nextPage = 1 } = {}) {
  const safeCollectionId = activeCollectionId.value === UNCLASSIFIED_COLLECTION_ID
    ? ''
    : String(activeCollectionId.value || '').trim();
  const items = await querySavedPapers({
    accessToken: accessToken.value,
    page: nextPage,
    pageSize: savedPapersPageSize.value || 20,
    collectionId: safeCollectionId,
    readStatus: readStatusFilter.value,
    keyword: keyword.value,
    sortBy: sortBy.value,
    sortOrder: sortOrder.value
  });
  const visibleItems = Array.isArray(items) ? items : [];
  const noteTasks = [];
  for (const item of visibleItems.slice(0, 24)) {
    if (!item?.saved_paper_id) continue;
    noteTasks.push(
      fetchSavedPaperNotes(item.saved_paper_id, { accessToken: accessToken.value })
    );
  }
  if (noteTasks.length) {
    await Promise.all(noteTasks);
  }
  const pendingEnrichmentItems = activeCollectionId.value === UNCLASSIFIED_COLLECTION_ID
    ? visiblePapers.value
    : visibleItems;
  void enrichMetadataForVisiblePapers(pendingEnrichmentItems);
}

async function changePage(nextPage) {
  await reloadSavedPapers({ nextPage });
}

async function setActiveCollection(collectionId) {
  activeCollectionId.value = collectionId;
  metadataEnrichAttemptedSet.value = new Set();
  if (collectionId === UNCLASSIFIED_COLLECTION_ID) {
    await ensureBookmarkIndexLoaded({ accessToken: accessToken.value, force: true });
  }
  await reloadSavedPapers({ nextPage: 1 });
}

async function promptCreateCollection() {
  const nextName = window.prompt('请输入分组名称');
  const safeName = String(nextName || '').trim();
  if (!safeName) return;
  try {
    await createCollectionQuick(safeName, { accessToken: accessToken.value });
  } catch {
    // error text is already handled by store message
  }
}

function normalizeReadStatus(status) {
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'completed') return 'completed';
  return 'unread';
}

function isRead(status) {
  return normalizeReadStatus(status) === 'completed';
}

async function toggleReadStatus(item) {
  const nextStatus = isRead(item?.read_status) ? 'unread' : 'completed';
  if (!item?.saved_paper_id || !nextStatus) return;
  try {
    await setSavedPaperReadStatus(item.saved_paper_id, nextStatus, { accessToken: accessToken.value });
    await reloadSavedPapers({ nextPage: savedPapersPage.value || 1 });
  } catch {
    // store keeps message
  }
}

async function removePaper(item) {
  const paperId = String(item?.paper_id || '').trim();
  if (!paperId) return;
  try {
    await togglePaperSaved({
      accessToken: accessToken.value,
      paperId,
      metadata: item?.metadata || null
    });
    await reloadSavedPapers({ nextPage: 1 });
    await fetchCollections({ accessToken: accessToken.value });
  } catch {
    // store keeps message
  }
}

function formatAuthors(authors) {
  const list = Array.isArray(authors) ? authors.filter(Boolean) : [];
  if (!list.length) return '--';
  if (list.length <= 3) return list.join(', ');
  return `${list.slice(0, 3).join(', ')} 等`;
}

function formatAbstract(text) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  if (normalized.length <= 260) return normalized;
  return `${normalized.slice(0, 257)}...`;
}

function shouldShowAbstract(text) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return false;
  // Landscape placeholder summary like "XX 的代表论文" should not render as a paper abstract card.
  if (/^.{1,80}的代表论文$/.test(normalized)) return false;
  return true;
}

function formatDateTime(value) {
  const source = String(value || '').trim();
  if (!source) return '--';
  const parsed = new Date(source);
  if (Number.isNaN(parsed.getTime())) return '--';
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, '0');
  const day = String(parsed.getDate()).padStart(2, '0');
  const hour = String(parsed.getHours()).padStart(2, '0');
  const minute = String(parsed.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day} ${hour}:${minute}`;
}

function formatPublicationTime(publicationDate, year) {
  const dateText = String(publicationDate || '').trim();
  if (dateText) {
    const parsed = new Date(dateText);
    if (!Number.isNaN(parsed.getTime())) {
      const parsedYear = parsed.getFullYear();
      const parsedMonth = String(parsed.getMonth() + 1).padStart(2, '0');
      const parsedDay = String(parsed.getDate()).padStart(2, '0');
      return `${parsedYear}-${parsedMonth}-${parsedDay}`;
    }
    return dateText;
  }
  if (Number.isFinite(Number(year))) {
    return String(Math.round(Number(year)));
  }
  return '--';
}

function formatImpactFactor(value) {
  if (!Number.isFinite(Number(value))) return '--';
  return Number(value).toFixed(2);
}

function needsMetadataEnrichment(item) {
  if (!item || typeof item !== 'object') return false;
  const impactFactor = Number(item?.metadata?.impact_factor);
  const fields = Array.isArray(item?.metadata?.fields_of_study)
    ? item.metadata.fields_of_study.map((entry) => String(entry || '').trim()).filter(Boolean)
    : [];
  return !Number.isFinite(impactFactor) || !fields.length;
}

async function enrichMetadataForVisiblePapers(items) {
  const list = Array.isArray(items) ? items : [];
  const candidates = [];
  const attempted = new Set(metadataEnrichAttemptedSet.value);
  for (const item of list) {
    const savedPaperId = String(item?.saved_paper_id || '').trim();
    if (!savedPaperId || attempted.has(savedPaperId)) continue;
    if (!needsMetadataEnrichment(item)) continue;
    attempted.add(savedPaperId);
    candidates.push(savedPaperId);
    if (candidates.length >= 8) break;
  }
  metadataEnrichAttemptedSet.value = attempted;
  if (!candidates.length) return;
  const results = await Promise.all(
    candidates.map(async (savedPaperId) => {
      const payload = await enrichSavedPaperMetadata(
        savedPaperId,
        { accessToken: accessToken.value, silent: true }
      );
      return {
        savedPaperId,
        success: Boolean(payload?.saved_paper_id)
      };
    })
  );
  for (const result of results) {
    if (result.success) continue;
    attempted.delete(result.savedPaperId);
  }
  metadataEnrichAttemptedSet.value = attempted;
}

function formatFields(fields) {
  const list = Array.isArray(fields) ? fields.map((item) => String(item || '').trim()).filter(Boolean) : [];
  if (!list.length) return '--';
  if (list.length <= 2) return list.join(' / ');
  return `${list.slice(0, 2).join(' / ')} +${list.length - 2}`;
}

function notesForPaper(savedPaperId) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  if (!safeSavedPaperId) return [];
  const notes = notesBySavedPaperId.value[safeSavedPaperId];
  return Array.isArray(notes) ? notes : [];
}

function isNoteEditorOpen(savedPaperId) {
  const safeSavedPaperId = String(savedPaperId || '').trim();
  if (!safeSavedPaperId) return false;
  return Boolean(noteEditorOpenMap.value[safeSavedPaperId]);
}

function isNotePanelVisible(item) {
  const safeSavedPaperId = String(item?.saved_paper_id || '').trim();
  if (!safeSavedPaperId) return false;
  return isNoteEditorOpen(safeSavedPaperId);
}

async function toggleNoteEditor(item) {
  const safeSavedPaperId = String(item?.saved_paper_id || '').trim();
  if (!safeSavedPaperId) return;
  const currentlyOpen = isNoteEditorOpen(safeSavedPaperId);
  noteEditorOpenMap.value = {
    ...noteEditorOpenMap.value,
    [safeSavedPaperId]: !currentlyOpen
  };
  if (!currentlyOpen) {
    await fetchSavedPaperNotes(safeSavedPaperId, {
      accessToken: accessToken.value,
      force: true
    });
  }
}

async function submitNote(item) {
  const safeSavedPaperId = String(item?.saved_paper_id || '').trim();
  if (!safeSavedPaperId) return;
  const draft = String(noteDraftMap.value[safeSavedPaperId] || '').trim();
  if (!draft) return;
  try {
    await addSavedPaperNote(safeSavedPaperId, draft, { accessToken: accessToken.value });
    noteDraftMap.value = {
      ...noteDraftMap.value,
      [safeSavedPaperId]: ''
    };
  } catch {
    // store keeps message
  }
}

async function removeNote(item, note) {
  const safeSavedPaperId = String(item?.saved_paper_id || '').trim();
  const safeNoteId = String(note?.note_id || '').trim();
  if (!safeSavedPaperId || !safeNoteId) return;
  try {
    await deleteSavedPaperNoteById(safeSavedPaperId, safeNoteId, { accessToken: accessToken.value });
  } catch {
    // store keeps message
  }
}

onMounted(async () => {
  await loadSession();
  if (!isAuthenticated.value) {
    router.replace({ name: 'home' });
    return;
  }
  await Promise.all([
    fetchCollections({ accessToken: accessToken.value }),
    reloadSavedPapers({ nextPage: 1 })
  ]);
});
</script>

<style scoped>
.collection-layout {
  min-height: calc(100vh - 110px);
  display: grid;
  gap: 14px;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
}

.collection-sidebar,
.collection-main {
  min-height: 0;
}

.collection-main {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.collection-main-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.collection-status-summary {
  color: var(--muted);
  font-size: 11px;
}

.collection-main-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow: auto;
}

.collection-filter-row {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 108px 108px auto;
  gap: 6px;
  margin-bottom: 0;
}

.collection-filter-input,
.collection-filter-select {
  width: 100%;
  height: 32px;
  border: 1px solid var(--line-2);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--text);
  font-size: 11px;
  line-height: 1;
  padding: 0 9px;
}

.collection-filter-select {
  appearance: none;
  background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%);
  background-position: calc(100% - 13px) 13px, calc(100% - 9px) 13px;
  background-size: 4px 4px, 4px 4px;
  background-repeat: no-repeat;
  padding-right: 24px;
}

.collection-filter-input:focus,
.collection-filter-select:focus {
  outline: 0;
  border-color: #c8c8c8;
}

.collection-query-btn {
  height: 32px;
  padding: 0 10px;
}

.collection-nav {
  display: grid;
  gap: 6px;
}

.collection-nav-item {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 9px;
  font-size: 11px;
  cursor: pointer;
  text-align: left;
}

.collection-nav-item:hover {
  background: var(--panel);
}

.collection-nav-item.is-active {
  border-color: var(--text);
  background: var(--panel);
}

.collection-name-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.collection-emoji {
  font-size: 14px;
  line-height: 1;
}

.collection-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.collection-create-btn {
  height: 32px;
  width: 32px;
  min-width: 32px;
  padding: 0;
}

.collection-create-btn svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.collection-paper-list {
  margin-top: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-content: start;
}

.collection-paper-card {
  position: relative;
  border: 1px solid var(--line);
  border-left: 2px solid var(--line-2);
  border-radius: var(--radius-md);
  background: var(--bg);
  padding: 12px;
  box-shadow: var(--shadow-soft);
  transition: box-shadow 0.2s ease, border-left-color 0.2s ease;
}

.collection-paper-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.collection-paper-card.is-read {
  border-left-color: var(--success);
}

.collection-card-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
}

.collection-info-area {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.collection-paper-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
}

.collection-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 16px;
}

.collection-meta-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.collection-meta-label {
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
  flex-shrink: 0;
}

.collection-meta-value {
  font-size: 12px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.collection-meta-value.mono {
  font-size: 11.5px;
}

.collection-meta-value.accent {
  color: var(--accent);
  font-weight: 500;
}

.collection-meta-value.tag {
  font-size: 11px;
  color: var(--muted);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 1px 6px;
  font-family: 'JetBrains Mono', 'Noto Sans SC', monospace;
}

.collection-abstract-block {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
}

.collection-icon-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--line-2);
  border-radius: var(--radius-sm);
  background: #fff;
  color: var(--text);
  padding: 0;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.collection-icon-btn svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.collection-icon-btn:hover {
  background: #f5f5f5;
}

.collection-icon-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  background: #fff5f2;
}

.collection-read-btn {
  color: var(--muted);
  background: var(--panel);
}

.collection-read-btn.is-read {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 35%, var(--line));
  background: color-mix(in srgb, var(--success) 8%, var(--bg));
}

.collection-star-btn {
  color: var(--muted);
}

.collection-star-btn.is-saved {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 35%, var(--line));
  background: color-mix(in srgb, var(--accent) 8%, var(--bg));
}

.collection-star-btn.is-saved svg {
  fill: currentColor;
}

.collection-paper-abstract {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.65;
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.collection-paper-notes {
  grid-column: 1 / -1;
  border-top: 1px solid var(--line);
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.collection-note-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.collection-note-title {
  margin: 0;
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.collection-note-add-btn {
  width: 28px;
  height: 28px;
  min-width: 28px;
}

.collection-note-sync {
  font-size: 11px;
  color: var(--muted);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.collection-note-sync-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: collection-note-pulse 1s ease-in-out infinite;
}

.collection-note-input {
  height: 32px;
  font-size: 12px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
}

.collection-note-input:focus {
  border-color: var(--line-2);
  background: var(--bg);
}

.collection-note-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 136px;
  overflow: auto;
}

.collection-note-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  gap: 8px;
}

.collection-note-content {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text);
  word-break: break-word;
}

.collection-note-remove {
  width: 18px;
  height: 18px;
  border: 1px solid var(--line-2);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--muted);
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease;
}

.collection-note-remove:hover {
  background: #f5f5f5;
  color: var(--accent);
}

.collection-note-remove svg {
  width: 10px;
  height: 10px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.collection-actions-area {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding-top: 2px;
}

.collection-note-slide-enter-active,
.collection-note-slide-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.collection-note-slide-enter-from,
.collection-note-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@keyframes collection-note-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.collection-pagination {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 980px) {
  .collection-layout {
    min-height: auto;
    grid-template-columns: 1fr;
  }

  .collection-main-body {
    overflow: visible;
  }

  .collection-card-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .collection-actions-area {
    justify-content: flex-start;
    padding-top: 0;
  }
}

@media (max-width: 768px) {
  .collection-filter-row {
    grid-template-columns: 1fr;
  }

  .collection-card-grid {
    grid-template-columns: 1fr;
  }

  .collection-actions-area {
    justify-content: flex-start;
    gap: 6px;
  }

  .collection-meta-grid {
    grid-template-columns: 1fr;
  }

}
</style>
