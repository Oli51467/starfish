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
                <span class="collection-name-wrap">
                  <span class="collection-name">全部论文</span>
                </span>
                <span class="collection-nav-count">{{ allCount }}</span>
              </button>
              <button
                class="collection-nav-item mono"
                :class="{ 'is-active': activeCollectionId === UNCLASSIFIED_COLLECTION_ID }"
                type="button"
                @click="setActiveCollection(UNCLASSIFIED_COLLECTION_ID)"
              >
                <span class="collection-name-wrap">
                  <span class="collection-name">未分组论文</span>
                </span>
                <span class="collection-nav-count">{{ unclassifiedCount }}</span>
              </button>
              <div
                v-for="item in customCollections"
                :key="item.collection_id"
                class="collection-nav-item collection-nav-item-custom"
                :class="{ 'is-active': activeCollectionId === item.collection_id }"
              >
                <button
                  class="collection-nav-main mono"
                  type="button"
                  @click="setActiveCollection(item.collection_id)"
                >
                  <span class="collection-name-wrap">
                    <span class="collection-emoji" aria-hidden="true">{{ item.emoji || '📁' }}</span>
                    <span class="collection-name">{{ item.name }}</span>
                  </span>
                  <span class="collection-nav-count">{{ item.paper_count }}</span>
                </button>
                <button
                  class="collection-nav-delete"
                  type="button"
                  :title="`删除分组 ${item.name}`"
                  :aria-label="`删除分组 ${item.name}`"
                  @click.stop="deleteCustomCollection(item)"
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
            </div>
          </div>
        </aside>

        <article class="panel collection-main">
          <div class="panel-head collection-main-head">
            <h2>{{ activeCollectionTitle }}</h2>
            <div class="collection-main-head-right">
              <div class="collection-status-summary mono">
                未读 {{ summaryUnreadCount }} · 阅读中 {{ summaryReadingCount }} · 已读 {{ summaryCompletedCount }}
              </div>
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
              <button
                class="btn mono collection-filter-refresh-btn"
                type="button"
                :disabled="signalRefreshing"
                @click="refreshSignalFeed"
              >
                {{ signalRefreshing ? '刷新中...' : '刷新动态' }}
              </button>
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
                      <div class="collection-meta-item is-right-meta">
                        <span class="collection-meta-label mono">论文作者</span>
                        <span class="collection-meta-value">{{ formatAuthors(item.metadata.authors) }}</span>
                      </div>
                      <div class="collection-meta-item">
                        <span class="collection-meta-label mono">发表时间</span>
                        <span class="collection-meta-value mono">{{ formatPublicationTime(item.metadata.publication_date, item.metadata.year) }}</span>
                      </div>
                      <div class="collection-meta-item is-right-meta">
                        <span class="collection-meta-label mono">影响因子</span>
                        <span class="collection-meta-value mono accent">{{ formatImpactFactor(item.metadata.impact_factor) }}</span>
                      </div>
                      <div class="collection-meta-item">
                        <span class="collection-meta-label mono">引用数</span>
                        <span class="collection-meta-value mono">{{ Number(item.metadata.citation_count || 0).toLocaleString() }}</span>
                      </div>
                      <div class="collection-meta-item is-right-meta">
                        <span class="collection-meta-label mono">论文领域</span>
                        <span class="collection-meta-value tag">{{ formatFields(item.metadata.fields_of_study) }}</span>
                      </div>
                    </div>
                    <div v-if="shouldShowAbstract(item.metadata.abstract)" class="collection-abstract-block">
                      <p class="collection-paper-abstract">
                        {{ formatAbstract(item.metadata.abstract) }}
                      </p>
                    </div>
                    <div
                      v-if="hasRefreshedSignals && paperSignalLinks(item).length"
                      class="collection-paper-signal-links"
                    >
                      <p class="collection-paper-signal-title mono">研究动态外链</p>
                      <div class="collection-paper-signal-link-list">
                        <a
                          v-for="link in paperSignalLinks(item)"
                          :key="`${item.saved_paper_id}-${link.url}`"
                          class="collection-paper-signal-link"
                          :href="link.url"
                          target="_blank"
                          rel="noopener noreferrer"
                          @click.stop
                        >
                          <span class="collection-paper-signal-link-label">{{ link.label }}</span>
                          <span class="collection-paper-signal-link-url mono">{{ link.displayUrl }}</span>
                        </a>
                      </div>
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
import { useGlobalConfirmDialog } from '../composables/useGlobalConfirmDialog';
import { useGlobalInputDialog } from '../composables/useGlobalInputDialog';
import { useAuthStore } from '../stores/authStore';
import { useCollectionStore } from '../stores/collectionStore';

const UNCLASSIFIED_COLLECTION_ID = '__unclassified__';

const router = useRouter();
const { accessToken, isAuthenticated, loadSession } = useAuthStore();
const { askForConfirm } = useGlobalConfirmDialog();
const { askForInput } = useGlobalInputDialog();
const {
  collections,
  savedPapers,
  savedPapersLoading,
  savedPapersErrorMessage,
  savedPapersPage,
  savedPapersPageSize,
  savedPapersTotal,
  savedPapersTotalPages,
  savedPaperIndexItems,
  notesBySavedPaperId,
  notesLoadingBySavedPaperId,
  signalEvents,
  signalRefreshing,
  fetchCollections,
  querySavedPapers,
  fetchSignalEvents,
  refreshSavedPaperSignals,
  setSavedPaperReadStatus,
  fetchSavedPaperNotes,
  addSavedPaperNote,
  deleteSavedPaperNoteById,
  createCollectionQuick,
  cleanupAutoGeneratedContent,
  removeCollectionQuick,
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
const hasRefreshedSignals = ref(false);
const allCount = computed(() => {
  return savedPaperIndexItems.value.length || savedPapersTotal.value || 0;
});
const unclassifiedCount = computed(() => {
  return savedPaperIndexItems.value.filter((item) => !Array.isArray(item?.collection_ids) || item.collection_ids.length === 0).length;
});
const summaryUnreadCount = computed(() => {
  return savedPaperIndexItems.value.filter((item) => String(item?.read_status || '').trim().toLowerCase() === 'unread').length;
});
const summaryReadingCount = computed(() => {
  return savedPaperIndexItems.value.filter((item) => String(item?.read_status || '').trim().toLowerCase() === 'reading').length;
});
const summaryCompletedCount = computed(() => {
  return savedPaperIndexItems.value.filter((item) => String(item?.read_status || '').trim().toLowerCase() === 'completed').length;
});
const collectionNameMap = computed(() => {
  const mapped = {};
  for (const item of collections.value) {
    const collectionId = String(item?.collection_id || '').trim();
    if (!collectionId) continue;
    mapped[collectionId] = String(item?.name || '').trim();
  }
  return mapped;
});
const customCollections = computed(() => {
  return collections.value.filter((item) => String(item?.collection_id || '').trim());
});

const activeCollectionTitle = computed(() => {
  const target = String(activeCollectionId.value || '').trim();
  if (!target) return '全部论文';
  if (target === UNCLASSIFIED_COLLECTION_ID) return '未分组论文';
  return collectionNameMap.value[target] || '论文分组';
});

const showPagination = computed(() => {
  if (activeCollectionId.value === UNCLASSIFIED_COLLECTION_ID) return false;
  return savedPapersTotalPages.value > 1;
});

const filteredIndexPapers = computed(() => {
  const keywordText = String(keyword.value || '').trim().toLowerCase();
  const status = String(readStatusFilter.value || '').trim().toLowerCase();
  const sorted = [...savedPaperIndexItems.value]
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

const visiblePapers = computed(() => {
  const target = String(activeCollectionId.value || '').trim();
  if (!target) {
    return savedPapers.value;
  }
  if (target === UNCLASSIFIED_COLLECTION_ID) {
    return filteredIndexPapers.value.filter((item) => !Array.isArray(item?.collection_ids) || item.collection_ids.length === 0);
  }
  return savedPapers.value;
});

const paperSignalLinksMap = computed(() => {
  const mapped = {};
  const dedupSets = {};
  for (const event of signalEvents.value) {
    const links = resolveEventExternalLinks(event);
    if (!links.length) continue;
    const keys = [
      String(event?.paper_id || '').trim(),
      String(event?.saved_paper_id || '').trim()
    ].filter(Boolean);
    for (const key of keys) {
      if (!mapped[key]) {
        mapped[key] = [];
        dedupSets[key] = new Set();
      }
      for (const link of links) {
        if (!link?.url || dedupSets[key].has(link.url)) continue;
        dedupSets[key].add(link.url);
        mapped[key].push(link);
      }
    }
  }
  return mapped;
});

function goHome() {
  router.push({ name: 'home' });
}

async function reloadSavedPapers({ nextPage = 1 } = {}) {
  const targetCollectionId = String(activeCollectionId.value || '').trim();
  const useSyntheticBucket = targetCollectionId === UNCLASSIFIED_COLLECTION_ID;
  if (useSyntheticBucket) {
    await ensureBookmarkIndexLoaded({ accessToken: accessToken.value, force: false });
    const localVisibleItems = Array.isArray(visiblePapers.value) ? visiblePapers.value : [];
    const noteTasks = [];
    for (const item of localVisibleItems.slice(0, 24)) {
      if (!item?.saved_paper_id) continue;
      noteTasks.push(
        fetchSavedPaperNotes(item.saved_paper_id, { accessToken: accessToken.value })
      );
    }
    if (noteTasks.length) {
      await Promise.all(noteTasks);
    }
    void enrichMetadataForVisiblePapers(localVisibleItems);
    return;
  }

  const safeCollectionId = targetCollectionId;
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
  void enrichMetadataForVisiblePapers(visibleItems);
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
  const nextName = await askForInput({
    title: '新建分组',
    message: '请输入分组名称。',
    placeholder: '例如：Transformer 阅读',
    confirmText: '创建',
    cancelText: '取消',
    required: true,
    requiredMessage: '请输入分组名称。',
    maxLength: 100
  });
  const safeName = String(nextName || '').trim();
  if (!safeName) return;
  try {
    await createCollectionQuick(safeName, { accessToken: accessToken.value });
  } catch {
    // store error message handled internally
  }
}

async function deleteCustomCollection(collection) {
  const collectionId = String(collection?.collection_id || '').trim();
  if (!collectionId) return;
  const collectionName = String(collection?.name || '该分组').trim() || '该分组';
  const confirmed = await askForConfirm({
    title: '删除分组',
    message: `确定删除「${collectionName}」吗？分组内论文将保留在“未分组论文”。`,
    confirmText: '删除',
    cancelText: '取消',
    danger: true
  });
  if (!confirmed) return;

  const deleted = await removeCollectionQuick(collectionId, { accessToken: accessToken.value });
  if (!deleted) return;

  await ensureBookmarkIndexLoaded({ accessToken: accessToken.value, force: true });
  if (String(activeCollectionId.value || '').trim() === collectionId) {
    activeCollectionId.value = '';
  }
  await reloadSavedPapers({ nextPage: 1 });
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

function normalizeExternalUrl(rawValue) {
  const text = String(rawValue || '').trim();
  if (!text) return '';
  if (/^https?:\/\//i.test(text)) return text;
  if (/^(?:dx\.)?doi\.org\/\S+/i.test(text)) return `https://${text}`;
  if (/^arxiv\.org\/abs\/\S+/i.test(text)) return `https://${text}`;
  if (/^doi:\s*/i.test(text)) {
    return `https://doi.org/${text.replace(/^doi:\s*/i, '').trim()}`;
  }
  if (/^10\.\d{4,9}\/\S+/i.test(text)) {
    return `https://doi.org/${text}`;
  }
  if (/^www\./i.test(text)) {
    return `https://${text}`;
  }
  return '';
}

function extractArxivId(rawValue) {
  const text = String(rawValue || '').trim();
  if (!text) return '';
  const urlMatched = text.match(/arxiv\.org\/abs\/([^?#\s]+)/i);
  if (urlMatched?.[1]) return urlMatched[1];
  const normalized = text.replace(/^arxiv:\s*/i, '').trim();
  if (/^\d{4}\.\d{4,5}(v\d+)?$/i.test(normalized)) return normalized;
  if (/^[a-z\-]+(?:\.[a-z\-]+)?\/\d{7}(v\d+)?$/i.test(normalized)) return normalized;
  return '';
}

function resolvePaperCanonicalUrl(paperId) {
  const safePaperId = String(paperId || '').trim();
  if (!safePaperId) return '';
  const normalized = normalizeExternalUrl(safePaperId);
  if (normalized) return normalized;
  const arxivId = extractArxivId(safePaperId);
  if (arxivId) return `https://arxiv.org/abs/${arxivId}`;
  return '';
}

function compactExternalUrl(url) {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname === '/' ? '' : parsed.pathname;
    return `${parsed.hostname}${path}`;
  } catch {
    return url;
  }
}

function appendEventLinksFromValue(rawValue, fallbackLabel, collector, depth = 0) {
  if (depth > 2 || rawValue == null) return;

  if (typeof rawValue === 'string') {
    const url = normalizeExternalUrl(rawValue);
    if (!url) return;
    collector({
      url,
      label: fallbackLabel,
      displayUrl: compactExternalUrl(url)
    });
    return;
  }

  if (Array.isArray(rawValue)) {
    for (const item of rawValue) {
      appendEventLinksFromValue(item, fallbackLabel, collector, depth + 1);
    }
    return;
  }

  if (typeof rawValue !== 'object') return;
  const label = String(rawValue?.title || rawValue?.label || rawValue?.name || fallbackLabel).trim() || fallbackLabel;
  const directUrl = normalizeExternalUrl(
    rawValue?.url
    || rawValue?.href
    || rawValue?.link
    || rawValue?.source_url
    || rawValue?.sourceUrl
  );
  if (directUrl) {
    collector({
      url: directUrl,
      label,
      displayUrl: compactExternalUrl(directUrl)
    });
    return;
  }

  appendEventLinksFromValue(rawValue?.links, fallbackLabel, collector, depth + 1);
  appendEventLinksFromValue(rawValue?.external_links || rawValue?.externalLinks, fallbackLabel, collector, depth + 1);
  appendEventLinksFromValue(rawValue?.references, fallbackLabel, collector, depth + 1);
  appendEventLinksFromValue(rawValue?.sources, fallbackLabel, collector, depth + 1);
}

function resolveEventExternalLinks(event) {
  const fallbackLabel = String(event?.title || '研究动态').trim() || '研究动态';
  const payload = event?.payload && typeof event.payload === 'object' ? event.payload : {};
  const links = [];
  const seen = new Set();
  const collect = (entry) => {
    if (!entry?.url || seen.has(entry.url)) return;
    seen.add(entry.url);
    links.push(entry);
  };

  appendEventLinksFromValue(payload, fallbackLabel, collect);
  appendEventLinksFromValue(payload?.links, fallbackLabel, collect);
  appendEventLinksFromValue(payload?.external_links || payload?.externalLinks, fallbackLabel, collect);
  appendEventLinksFromValue(payload?.url || payload?.link || payload?.href, fallbackLabel, collect);

  if (!links.length) {
    const fallbackUrl = resolvePaperCanonicalUrl(event?.paper_id);
    if (fallbackUrl) {
      links.push({
        url: fallbackUrl,
        label: fallbackLabel,
        displayUrl: compactExternalUrl(fallbackUrl)
      });
    }
  }
  return links;
}

function paperSignalLinks(item) {
  const paperId = String(item?.paper_id || '').trim();
  const savedPaperId = String(item?.saved_paper_id || '').trim();
  const byPaperId = paperId ? (paperSignalLinksMap.value[paperId] || []) : [];
  const bySavedPaperId = savedPaperId ? (paperSignalLinksMap.value[savedPaperId] || []) : [];
  if (!byPaperId.length) return bySavedPaperId;
  if (!bySavedPaperId.length) return byPaperId;
  const merged = [];
  const seen = new Set();
  for (const link of [...byPaperId, ...bySavedPaperId]) {
    if (!link?.url || seen.has(link.url)) continue;
    seen.add(link.url);
    merged.push(link);
  }
  return merged;
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

async function refreshSignalFeed() {
  const targetCollectionId = String(activeCollectionId.value || '').trim();
  const useSyntheticBucket = targetCollectionId === UNCLASSIFIED_COLLECTION_ID;
  await refreshSavedPaperSignals({
    accessToken: accessToken.value,
    collectionId: useSyntheticBucket ? '' : targetCollectionId,
    limit: 50,
    forceRefresh: false
  });
  await fetchSignalEvents({
    accessToken: accessToken.value,
    page: 1,
    pageSize: 50,
    unreadOnly: false
  });
  hasRefreshedSignals.value = true;
}

onMounted(async () => {
  await loadSession();
  if (!isAuthenticated.value) {
    router.replace({ name: 'home' });
    return;
  }
  await cleanupAutoGeneratedContent({ accessToken: accessToken.value });
  await Promise.all([
    fetchCollections({ accessToken: accessToken.value }),
    ensureBookmarkIndexLoaded({ accessToken: accessToken.value, force: true }),
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

.collection-main-head-right {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0;
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
  grid-template-columns: minmax(220px, 1fr) 108px 108px auto auto;
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

.collection-filter-refresh-btn {
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
  justify-content: flex-start;
  gap: 8px;
  padding: 6px 9px;
  font-size: 11px;
  cursor: pointer;
  text-align: left;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  overflow: hidden;
}

.collection-nav-item:hover {
  background: var(--panel);
}

.collection-nav-item.is-active {
  border-color: var(--text);
  background: var(--panel);
}

.collection-nav-item-custom {
  padding: 0 4px 0 0;
  gap: 0;
  align-items: stretch;
}

.collection-nav-main {
  border: 0;
  background: transparent;
  color: inherit;
  padding: 6px 9px;
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  text-align: left;
  cursor: pointer;
  min-width: 0;
  flex: 1 1 auto;
}

.collection-nav-main:focus-visible {
  outline: 0;
}

.collection-nav-delete {
  width: 24px;
  height: 24px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  cursor: pointer;
  align-self: center;
  flex: 0 0 auto;
}

.collection-nav-delete svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.collection-nav-delete:hover {
  border-color: color-mix(in srgb, var(--accent) 46%, var(--line));
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--bg));
}

.collection-name-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
}

.collection-emoji {
  font-size: 14px;
  line-height: 1;
}

.collection-name {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.collection-nav-count {
  margin-left: auto;
  flex: 0 0 auto;
  text-align: right;
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
  margin-top: 10px;
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
  gap: 4px 12px;
}

.collection-meta-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.collection-meta-item.is-right-meta {
  transform: translateX(-8px);
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

.collection-paper-signal-links {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  padding: 8px 10px;
  display: grid;
  gap: 6px;
}

.collection-paper-signal-title {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.collection-paper-signal-link-list {
  display: grid;
  gap: 5px;
}

.collection-paper-signal-link {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--text);
  text-decoration: none;
  padding: 6px 8px;
  display: grid;
  gap: 2px;
  transition: border-color 0.2s ease, background-color 0.2s ease;
}

.collection-paper-signal-link:hover {
  border-color: var(--line-2);
  background: color-mix(in srgb, var(--panel) 76%, var(--bg));
}

.collection-paper-signal-link-label {
  font-size: 11px;
  line-height: 1.45;
  color: var(--text);
}

.collection-paper-signal-link-url {
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  .collection-main-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .collection-main-head-right {
    width: auto;
    justify-content: flex-end;
  }

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

  .collection-meta-item.is-right-meta {
    transform: none;
  }

}
</style>
