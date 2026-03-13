const DEFAULT_API_BASE_URL = 'http://localhost:14032';

function getApiBaseUrl() {
  return (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/$/, '');
}

async function request(path, options = {}) {
  const response = await fetch(`${getApiBaseUrl()}${path}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data?.detail || `HTTP ${response.status}`;
    throw new Error(typeof message === 'string' ? message : `HTTP ${response.status}`);
  }
  return data;
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

export function buildKnowledgeGraph(payload) {
  return request('/api/graphrag/build', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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

export function getLineage(paperId, { ancestorDepth = 2, descendantDepth = 2, citationTypes = [] } = {}) {
  const query = new URLSearchParams();
  query.set('ancestor_depth', String(ancestorDepth));
  query.set('descendant_depth', String(descendantDepth));
  for (const type of citationTypes) {
    query.append('citation_types', type);
  }
  return request(`/api/lineage/${encodeURIComponent(paperId)}?${query.toString()}`);
}
