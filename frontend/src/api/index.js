const DEFAULT_API_BASE_URL = 'http://localhost:14032';
const LANDSCAPE_TASK_POLL_INTERVAL_MS = 700;

function getApiBaseUrl() {
  return (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/$/, '');
}

function getWsBaseUrl() {
  const apiBaseUrl = getApiBaseUrl();
  if (apiBaseUrl.startsWith('https://')) {
    return `wss://${apiBaseUrl.slice('https://'.length)}`;
  }
  if (apiBaseUrl.startsWith('http://')) {
    return `ws://${apiBaseUrl.slice('http://'.length)}`;
  }
  return apiBaseUrl;
}

async function request(path, options = {}) {
  const baseUrl = getApiBaseUrl();
  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, options);
  } catch {
    throw new Error(`无法连接后端服务（${baseUrl}），请先启动后端。`);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data?.detail || `HTTP ${response.status}`;
    throw new Error(typeof message === 'string' ? message : `HTTP ${response.status}`);
  }
  return data;
}

function buildAuthHeaders(accessToken, baseHeaders = {}) {
  const token = String(accessToken || '').trim();
  if (!token) return baseHeaders;
  return {
    ...baseHeaders,
    Authorization: `Bearer ${token}`
  };
}

export function authWithGoogle(credential) {
  return request('/api/auth/google', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential })
  });
}

export function getAuthMe(accessToken) {
  return request('/api/auth/me', {
    headers: buildAuthHeaders(accessToken)
  });
}

export function generateMap(payload) {
  return request('/api/map/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export function getTask(taskId) {
  return request(`/api/tasks/${encodeURIComponent(taskId)}`);
}

export function getMap(mapId) {
  return request(`/api/map/${encodeURIComponent(mapId)}`);
}

export function buildKnowledgeGraph(payload, accessToken = '') {
  return request('/api/graphrag/build', {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
}

export function retrieveKnowledgePapers(payload) {
  return request('/api/graphrag/retrieve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export function getKnowledgeGraph(graphId) {
  return request(`/api/graphrag/${encodeURIComponent(graphId)}`);
}

export function getResearchHistoryList({ page = 1, pageSize = 10, accessToken = '' } = {}) {
  const query = new URLSearchParams();
  query.set('page', String(Math.max(1, Number(page) || 1)));
  query.set('page_size', String(Math.max(1, Math.min(50, Number(pageSize) || 10))));
  return request(`/api/research-history?${query.toString()}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export function getResearchHistoryDetail(historyId, { accessToken = '' } = {}) {
  return request(`/api/research-history/${encodeURIComponent(historyId)}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export function deleteResearchHistory(historyId, { accessToken = '' } = {}) {
  return request(`/api/research-history/${encodeURIComponent(historyId)}`, {
    method: 'DELETE',
    headers: buildAuthHeaders(accessToken)
  });
}

export function batchDeleteResearchHistory(historyIds, { accessToken = '' } = {}) {
  const payload = {
    history_ids: Array.isArray(historyIds) ? historyIds : []
  };
  return request('/api/research-history/batch-delete', {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
}

export function updateResearchHistoryLineageStatus(payload, accessToken = '') {
  return request('/api/research-history/lineage-status', {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload || {})
  });
}

export function getPaperSignal(paperId, { accessToken = '', forceRefresh = false } = {}) {
  const query = new URLSearchParams();
  query.set('force_refresh', forceRefresh ? 'true' : 'false');
  return request(`/api/paper-signals/${encodeURIComponent(paperId)}?${query.toString()}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export function refreshPaperSignals(
  { collectionId = '', limit = 20, forceRefresh = false } = {},
  { accessToken = '' } = {}
) {
  return request('/api/paper-signals/refresh', {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      collection_id: String(collectionId || '').trim(),
      limit: Math.max(1, Math.min(50, Number(limit) || 20)),
      force_refresh: Boolean(forceRefresh)
    })
  });
}

export function getPaperSignalEvents(
  { page = 1, pageSize = 10, unreadOnly = false, paperId = '', savedPaperId = '' } = {},
  { accessToken = '' } = {}
) {
  const query = new URLSearchParams();
  query.set('page', String(Math.max(1, Number(page) || 1)));
  query.set('page_size', String(Math.max(1, Math.min(50, Number(pageSize) || 10))));
  query.set('unread_only', unreadOnly ? 'true' : 'false');
  const safePaperId = String(paperId || '').trim();
  const safeSavedPaperId = String(savedPaperId || '').trim();
  if (safePaperId) query.set('paper_id', safePaperId);
  if (safeSavedPaperId) query.set('saved_paper_id', safeSavedPaperId);
  return request(`/api/paper-signals/events?${query.toString()}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export function markPaperSignalEventRead(eventId, { accessToken = '' } = {}) {
  return request(`/api/paper-signals/events/${encodeURIComponent(eventId)}/read`, {
    method: 'PATCH',
    headers: buildAuthHeaders(accessToken)
  });
}

export function startLandscapeGeneration(payload, accessToken = '') {
  return request('/api/landscape/generate', {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
}

export function getLandscapeTask(taskId, accessToken = '') {
  return request(`/api/landscape/task/${encodeURIComponent(taskId)}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export function getLandscapeResult(taskId, accessToken = '') {
  return request(`/api/landscape/result/${encodeURIComponent(taskId)}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export async function generateLandscape(query, onProgress, options = {}) {
  const safeQuery = String(query || '').trim();
  if (!safeQuery) {
    throw new Error('query is required');
  }

  const rawRange = Number(options?.paperRangeYears);
  const paperRangeYears = Number.isFinite(rawRange) && rawRange > 0 ? Math.min(30, Math.round(rawRange)) : null;
  const quickMode = Boolean(options?.quickMode);
  const accessToken = String(options?.accessToken || '').trim();
  const created = await startLandscapeGeneration({
    query: safeQuery,
    ...(paperRangeYears ? { paper_range_years: paperRangeYears } : {}),
    quick_mode: quickMode
  }, accessToken);
  const taskId = created?.task_id;
  if (!taskId) {
    throw new Error('landscape task id missing');
  }

  while (true) {
    const task = await getLandscapeTask(taskId, accessToken);
    if (typeof onProgress === 'function') {
      onProgress(task);
    }

    if (task.status === 'completed') {
      for (let attempt = 0; attempt < 4; attempt += 1) {
        try {
          return await getLandscapeResult(taskId, accessToken);
        } catch (error) {
          if (attempt >= 3) throw error;
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
      }
    }
    if (task.status === 'failed') {
      throw new Error(task.error || task.message || '领域全景生成失败');
    }
    await new Promise((resolve) => setTimeout(resolve, LANDSCAPE_TASK_POLL_INTERVAL_MS));
  }
}

export function getNeo4jStatus() {
  return request('/api/graphrag/neo4j/status');
}

export function getReadingList(mapId, { focusArea = '', maxPapers = 20 } = {}) {
  const query = new URLSearchParams();
  if (focusArea) query.set('focus_area', focusArea);
  query.set('max_papers', String(maxPapers));
  return request(`/api/reading-list/${encodeURIComponent(mapId)}?${query.toString()}`);
}

export function getGaps(mapId, { gapTypes = [], minScore = 60 } = {}) {
  const query = new URLSearchParams();
  for (const type of gapTypes) {
    query.append('gap_types', type);
  }
  query.set('min_score', String(minScore));
  return request(`/api/gaps/${encodeURIComponent(mapId)}?${query.toString()}`);
}

export function getLineage(
  paperId,
  { ancestorDepth = 2, descendantDepth = 2, citationTypes = [], forceRefresh = false } = {}
) {
  const query = new URLSearchParams();
  query.set('ancestor_depth', String(ancestorDepth));
  query.set('descendant_depth', String(descendantDepth));
  query.set('force_refresh', forceRefresh ? 'true' : 'false');
  for (const type of citationTypes) {
    query.append('citation_types', type);
  }
  return request(`/api/lineage/${encodeURIComponent(paperId)}?${query.toString()}`);
}

export function startResearchSession(payload, { accessToken = '' } = {}) {
  return request('/api/research/start', {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload || {})
  });
}

export function getActiveResearchSession({ accessToken = '' } = {}) {
  return request('/api/research/active', {
    headers: buildAuthHeaders(accessToken)
  });
}

export function resumeResearchSession(sessionId, feedback = '', { accessToken = '' } = {}) {
  return request(`/api/research/resume/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ feedback: String(feedback || '') })
  });
}

export function stopResearchSession(sessionId, { accessToken = '' } = {}) {
  return request(`/api/research/stop/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    headers: buildAuthHeaders(accessToken)
  });
}

export function getResearchSession(sessionId, { accessToken = '' } = {}) {
  return request(`/api/research/session/${encodeURIComponent(sessionId)}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export function createResearchWebSocket(sessionId, accessToken = '') {
  const token = String(accessToken || '').trim();
  const wsBase = getWsBaseUrl();
  const url = `${wsBase}/api/research/ws/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(token)}`;
  return new WebSocket(url);
}

export function createCollection(payload, { accessToken = '' } = {}) {
  return request('/api/collections', {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload || {})
  });
}

export function getCollections({ accessToken = '', manualOnly = false } = {}) {
  const query = new URLSearchParams();
  if (manualOnly) query.set('manual_only', 'true');
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return request(`/api/collections${suffix}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export function updateCollection(collectionId, payload, { accessToken = '' } = {}) {
  return request(`/api/collections/${encodeURIComponent(collectionId)}`, {
    method: 'PUT',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload || {})
  });
}

export function removeCollection(collectionId, { accessToken = '' } = {}) {
  return request(`/api/collections/${encodeURIComponent(collectionId)}`, {
    method: 'DELETE',
    headers: buildAuthHeaders(accessToken)
  });
}

export function cleanupAutoGeneratedCollectionsAndPapers({ accessToken = '' } = {}) {
  return request('/api/collections/cleanup-auto', {
    method: 'POST',
    headers: buildAuthHeaders(accessToken)
  });
}

export function savePaper(payload, { accessToken = '' } = {}) {
  return request('/api/saved-papers', {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload || {})
  });
}

export function getSavedPapers(
  {
    page = 1,
    pageSize = 20,
    collectionId = '',
    manualOnly = false,
    readStatus = '',
    keyword = '',
    sortBy = 'saved_at',
    sortOrder = 'desc',
    accessToken = ''
  } = {}
) {
  const query = new URLSearchParams();
  query.set('page', String(Math.max(1, Number(page) || 1)));
  query.set('page_size', String(Math.max(1, Math.min(50, Number(pageSize) || 20))));
  if (String(collectionId || '').trim()) query.set('collection_id', String(collectionId).trim());
  if (manualOnly) query.set('manual_only', 'true');
  if (String(readStatus || '').trim()) query.set('read_status', String(readStatus).trim());
  if (String(keyword || '').trim()) query.set('keyword', String(keyword).trim());
  query.set('sort_by', String(sortBy || 'saved_at').trim());
  query.set('sort_order', String(sortOrder || 'desc').trim());
  return request(`/api/saved-papers?${query.toString()}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export function removeSavedPaper(savedPaperId, { accessToken = '' } = {}) {
  return request(`/api/saved-papers/${encodeURIComponent(savedPaperId)}`, {
    method: 'DELETE',
    headers: buildAuthHeaders(accessToken)
  });
}

export function updateSavedPaperStatus(savedPaperId, payload, { accessToken = '' } = {}) {
  return request(`/api/saved-papers/${encodeURIComponent(savedPaperId)}/status`, {
    method: 'PATCH',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload || {})
  });
}

export function enrichSavedPaperMetadata(savedPaperId, { accessToken = '', force = false } = {}) {
  const query = new URLSearchParams();
  query.set('force', force ? 'true' : 'false');
  return request(`/api/saved-papers/${encodeURIComponent(savedPaperId)}/enrich-metadata?${query.toString()}`, {
    method: 'POST',
    headers: buildAuthHeaders(accessToken)
  });
}

export function getSavedPaperNotes(savedPaperId, { accessToken = '', limit = 30 } = {}) {
  const query = new URLSearchParams();
  query.set('limit', String(Math.max(1, Math.min(100, Number(limit) || 30))));
  return request(`/api/saved-papers/${encodeURIComponent(savedPaperId)}/notes?${query.toString()}`, {
    headers: buildAuthHeaders(accessToken)
  });
}

export function createSavedPaperNote(savedPaperId, payload, { accessToken = '' } = {}) {
  return request(`/api/saved-papers/${encodeURIComponent(savedPaperId)}/notes`, {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload || {})
  });
}

export function removeSavedPaperNote(savedPaperId, noteId, { accessToken = '' } = {}) {
  return request(`/api/saved-papers/${encodeURIComponent(savedPaperId)}/notes/${encodeURIComponent(noteId)}`, {
    method: 'DELETE',
    headers: buildAuthHeaders(accessToken)
  });
}

export function attachSavedPaperToCollection(collectionId, payload, { accessToken = '' } = {}) {
  return request(`/api/collections/${encodeURIComponent(collectionId)}/papers`, {
    method: 'POST',
    headers: buildAuthHeaders(accessToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload || {})
  });
}

export function detachSavedPaperFromCollection(collectionId, savedPaperId, { accessToken = '' } = {}) {
  return request(`/api/collections/${encodeURIComponent(collectionId)}/papers/${encodeURIComponent(savedPaperId)}`, {
    method: 'DELETE',
    headers: buildAuthHeaders(accessToken)
  });
}
