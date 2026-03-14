const QUERY_NODE_ID = 'seed:query';
const MAX_PAPER_NODES = 24;
const MAX_DOMAIN_NODES = 16;
const MAX_PAPER_RELATED_EDGES = 34;
const MAX_DOMAIN_RELATED_EDGES = 16;
const MAX_PANORAMA_PAPER_NODES = 80;
const MIN_ASSOCIATION_RATE = 0.02;

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function safeNumber(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return parsed;
}

export function normalizeRate(value) {
  return clamp(safeNumber(value, 0), 0, 1);
}

function compactTokens(text) {
  return String(text || '')
    .toLowerCase()
    .match(/[a-z0-9]{2,}/g) || [];
}

function stripNodePrefix(value) {
  return String(value || '')
    .replace(/^(paper|entity|domain|seed)\s*[:：_-]\s*/i, '')
    .trim();
}

function isLikelyIdentifier(value) {
  const text = String(value || '').trim();
  if (!text) return true;
  const upper = text.toUpperCase();
  if (
    upper.startsWith('PAPER:')
    || upper.startsWith('ENTITY:')
    || upper.startsWith('DOMAIN:')
    || upper.startsWith('CORPUSID:')
    || upper.startsWith('DOI:')
    || upper.startsWith('ARXIV:')
  ) {
    return true;
  }
  if (/^10\.\d{4,9}\//.test(text)) return true;
  if (/^[A-Z]\d{6,}$/.test(upper)) return true;
  if (/^[0-9a-f]{24,}$/i.test(text)) return true;
  if (/^https?:\/\/\S+$/i.test(text)) return true;
  if (text.length >= 28 && /^[A-Za-z0-9:_\-./]+$/.test(text)) return true;
  return false;
}

export function resolveNodeName(node) {
  const labelRaw = String(node?.label || '').trim();
  const metaTitleRaw = String(node?.meta?.title || '').trim();
  const idRaw = String(node?.id || '').trim();
  const label = stripNodePrefix(labelRaw);
  const metaTitle = stripNodePrefix(metaTitleRaw);
  const cleanId = stripNodePrefix(idRaw);

  if (label && !isLikelyIdentifier(labelRaw)) return label;
  if (metaTitle && !isLikelyIdentifier(metaTitleRaw)) return metaTitle;
  if (cleanId && !isLikelyIdentifier(idRaw)) return cleanId;
  return label || metaTitle || cleanId || '未命名节点';
}

export function shortLabel(text, limit = 22) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  if (!value) return '';
  if (value.length <= limit) return value;
  return `${value.slice(0, Math.max(0, limit - 3))}...`;
}

function fallbackRelevance(name, query) {
  const queryTokens = new Set(compactTokens(query));
  if (!queryTokens.size) return 0;
  const nameTokens = new Set(compactTokens(name));
  const overlap = [...queryTokens].filter((token) => nameTokens.has(token)).length;
  return clamp(overlap / queryTokens.size, 0, 1);
}

function normalizePaperNode(node, query) {
  const name = resolveNodeName(node);
  const relevance = normalizeRate(node?.meta?.relevance ?? fallbackRelevance(name, query));
  const citationCount = safeNumber(node?.meta?.citation_count, 0);
  const score = normalizeRate(node?.score);
  return {
    ...node,
    kind: 'paper',
    name,
    relevance,
    citationCount,
    score,
    size: safeNumber(node?.size, 1)
  };
}

function normalizeDomainNode(node) {
  const name = resolveNodeName(node);
  return {
    ...node,
    kind: 'domain',
    name,
    relevance: normalizeRate(node?.meta?.relevance ?? node?.score),
    size: safeNumber(node?.size, 1)
  };
}

function normalizeEntityNode(node, query) {
  const name = resolveNodeName(node);
  const relevance = normalizeRate(node?.meta?.relevance ?? node?.score ?? fallbackRelevance(name, query));
  return {
    ...node,
    kind: 'entity',
    name,
    relevance,
    score: normalizeRate(node?.score),
    size: safeNumber(node?.size, 1)
  };
}

function buildQueryNode(query) {
  const label = shortLabel(query || '中心论文', 22) || '中心论文';
  return {
    id: QUERY_NODE_ID,
    type: 'seed',
    kind: 'seed',
    label,
    name: label,
    relevance: 1,
    score: 1,
    size: 14,
    meta: {
      query: String(query || '').trim()
    }
  };
}

function sortByRelevance(left, right) {
  if (right.relevance !== left.relevance) return right.relevance - left.relevance;
  if ((right.citationCount || 0) !== (left.citationCount || 0)) {
    return (right.citationCount || 0) - (left.citationCount || 0);
  }
  return (right.score || 0) - (left.score || 0);
}

function pickPaperPeerEdges(rawEdges, selectedPaperIds) {
  return (rawEdges || [])
    .filter((edge) => edge?.relation === 'related')
    .filter((edge) => selectedPaperIds.has(String(edge?.source || '')) && selectedPaperIds.has(String(edge?.target || '')))
    .map((edge, index) => ({
      id: `paper-peer-${index}`,
      source: String(edge.source),
      target: String(edge.target),
      relation: 'peer_related',
      kind: 'peer',
      relevance: normalizeRate(edge?.weight),
      meta: edge?.meta || {}
    }))
    .filter((edge) => edge.relevance > MIN_ASSOCIATION_RATE)
    .sort((left, right) => right.relevance - left.relevance)
    .slice(0, MAX_PAPER_RELATED_EDGES);
}

function buildPaperGraph(nodesRaw, edgesRaw, query) {
  const papers = nodesRaw
    .filter((node) => node?.type === 'paper')
    .map((node) => normalizePaperNode(node, query))
    .sort(sortByRelevance);

  const selectedPapers = papers
    .filter((paper) => paper.relevance > MIN_ASSOCIATION_RATE)
    .slice(0, MAX_PAPER_NODES);
  const centerNode = buildQueryNode(query);
  const selectedPaperIds = new Set(selectedPapers.map((paper) => paper.id));

  const centerEdges = selectedPapers.map((paper) => ({
    id: `seed-paper-${paper.id}`,
    source: QUERY_NODE_ID,
    target: paper.id,
    relation: 'seed_related',
    kind: 'center',
    relevance: paper.relevance,
    meta: {
      relation_label: '与输入论文关联'
    }
  }));

  const peerEdges = pickPaperPeerEdges(edgesRaw, selectedPaperIds);
  const nodes = [centerNode, ...selectedPapers];
  const edges = [...centerEdges, ...peerEdges];

  return {
    key: 'paper',
    title: '论文知识图谱',
    description: '以检索输入为中心，边越深表示论文关联度越高，节点距离越近。',
    centerNodeId: QUERY_NODE_ID,
    nodes,
    edges,
    counts: {
      seed: 1,
      paper: selectedPapers.length,
      domain: 0,
      edges: edges.length
    }
  };
}

function mapDomainPapers(edgesRaw, paperById, domainById) {
  const mapping = new Map();

  for (const edge of edgesRaw || []) {
    if (edge?.relation !== 'belongs_to') continue;
    const source = String(edge?.source || '');
    const target = String(edge?.target || '');

    let paperId = '';
    let domainId = '';
    if (paperById.has(source) && domainById.has(target)) {
      paperId = source;
      domainId = target;
    } else if (paperById.has(target) && domainById.has(source)) {
      paperId = target;
      domainId = source;
    }
    if (!paperId || !domainId) continue;

    const set = mapping.get(domainId) || new Set();
    set.add(paperId);
    mapping.set(domainId, set);
  }

  return mapping;
}

function buildDomainPeerEdges(domains) {
  const edges = [];
  for (let leftIndex = 0; leftIndex < domains.length; leftIndex += 1) {
    const left = domains[leftIndex];
    const leftSet = new Set(left.relatedPaperIds || []);
    if (!leftSet.size) continue;

    for (let rightIndex = leftIndex + 1; rightIndex < domains.length; rightIndex += 1) {
      const right = domains[rightIndex];
      const rightSet = new Set(right.relatedPaperIds || []);
      if (!rightSet.size) continue;

      const sharedCount = [...leftSet].filter((paperId) => rightSet.has(paperId)).length;
      if (!sharedCount) continue;

      const unionCount = new Set([...leftSet, ...rightSet]).size;
      const overlap = unionCount ? sharedCount / unionCount : 0;
      const relevance = clamp(overlap * 0.65 + ((left.relevance + right.relevance) / 2) * 0.35, 0, 1);
      if (relevance < MIN_ASSOCIATION_RATE) continue;

      edges.push({
        id: `domain-peer-${left.id}-${right.id}`,
        source: left.id,
        target: right.id,
        relation: 'domain_peer',
        kind: 'peer',
        relevance,
        meta: {
          shared_papers: String(sharedCount)
        }
      });
    }
  }

  return edges
    .sort((left, right) => right.relevance - left.relevance)
    .slice(0, MAX_DOMAIN_RELATED_EDGES);
}

function buildDomainGraph(nodesRaw, edgesRaw, query) {
  const papers = nodesRaw
    .filter((node) => node?.type === 'paper')
    .map((node) => normalizePaperNode(node, query));
  const domains = nodesRaw
    .filter((node) => node?.type === 'domain')
    .map(normalizeDomainNode);

  const paperById = new Map(papers.map((paper) => [paper.id, paper]));
  const domainById = new Map(domains.map((domain) => [domain.id, domain]));
  const domainPaperMapping = mapDomainPapers(edgesRaw, paperById, domainById);

  const rankedDomains = domains
    .map((domain) => {
      const paperIds = [...(domainPaperMapping.get(domain.id) || new Set())];
      const relatedPapers = paperIds
        .map((paperId) => paperById.get(paperId))
        .filter(Boolean)
        .sort(sortByRelevance);
      const relevances = relatedPapers.map((paper) => paper.relevance);
      const avgRelevance = relevances.length
        ? relevances.reduce((sum, current) => sum + current, 0) / relevances.length
        : 0;
      const maxRelevance = relevances[0] || 0;
      const mergedRelevance = relevances.length
        ? clamp(maxRelevance * 0.72 + avgRelevance * 0.28, 0, 1)
        : domain.relevance;
      const relevance = clamp(Math.max(mergedRelevance, domain.relevance * 0.5), 0, 1);
      const topRelated = relatedPapers.slice(0, 6).map((paper) => ({
        id: paper.id,
        title: paper.name,
        relevance: paper.relevance
      }));
      return {
        ...domain,
        relevance,
        relatedPaperIds: paperIds,
        meta: {
          ...domain.meta,
          paper_count: String(paperIds.length),
          avg_relevance: avgRelevance.toFixed(3),
          related_papers: topRelated
        }
      };
    })
    .sort((left, right) => {
      if (right.relevance !== left.relevance) return right.relevance - left.relevance;
      return (right.relatedPaperIds?.length || 0) - (left.relatedPaperIds?.length || 0);
    });

  const selectedDomains = rankedDomains.slice(0, MAX_DOMAIN_NODES);
  const filteredDomains = selectedDomains.filter((domain) => domain.relevance > MIN_ASSOCIATION_RATE);
  const centerNode = buildQueryNode(query);

  const centerEdges = filteredDomains.map((domain) => ({
    id: `seed-domain-${domain.id}`,
    source: QUERY_NODE_ID,
    target: domain.id,
    relation: 'seed_related',
    kind: 'center',
    relevance: domain.relevance,
    meta: {
      relation_label: '与输入论文关联'
    }
  }));

  const peerEdges = buildDomainPeerEdges(filteredDomains);
  const nodes = [centerNode, ...filteredDomains];
  const edges = [...centerEdges, ...peerEdges];

  return {
    key: 'domain',
    title: '领域知识图谱',
    description: '以检索输入为中心，边越深表示领域关联度越高，节点距离越近。',
    centerNodeId: QUERY_NODE_ID,
    nodes,
    edges,
    counts: {
      seed: 1,
      paper: 0,
      domain: filteredDomains.length,
      edges: edges.length
    }
  };
}

function buildPanoramaGraph(nodesRaw, edgesRaw, query) {
  const papers = nodesRaw
    .filter((node) => node?.type === 'paper')
    .map((node) => normalizePaperNode(node, query))
    .filter((paper) => paper.relevance > MIN_ASSOCIATION_RATE)
    .sort(sortByRelevance)
    .slice(0, MAX_PANORAMA_PAPER_NODES);

  const centerNode = buildQueryNode(query);
  const paperIds = new Set(papers.map((paper) => String(paper.id || '')));

  const centerEdges = papers.map((paper) => ({
    id: `panorama-seed-${paper.id}`,
    source: QUERY_NODE_ID,
    target: paper.id,
    relation: 'seed_related',
    kind: 'center',
    relevance: paper.relevance,
    meta: {
      relation_label: '由种子论文延伸'
    }
  }));

  const peerEdges = (edgesRaw || [])
    .filter((edge) => edge?.relation === 'related')
    .filter((edge) => paperIds.has(String(edge?.source || '')) && paperIds.has(String(edge?.target || '')))
    .map((edge, index) => ({
      id: String(edge?.id || `panorama-peer-${index}`),
      source: String(edge.source || ''),
      target: String(edge.target || ''),
      relation: 'peer_related',
      kind: 'peer',
      relevance: normalizeRate(edge?.weight),
      meta: edge?.meta || {}
    }))
    .filter((edge) => edge.source && edge.target && edge.relevance > MIN_ASSOCIATION_RATE)
    .sort((left, right) => right.relevance - left.relevance);

  const nodes = [centerNode, ...papers];
  const edges = [...centerEdges, ...peerEdges];

  return {
    key: 'panorama',
    title: '全景论文知识图谱',
    description: '展示与种子论文强相关、并由其延伸出的论文网络。',
    centerNodeId: QUERY_NODE_ID,
    nodes,
    edges,
    counts: {
      seed: 1,
      paper: papers.length,
      domain: 0,
      edges: edges.length
    }
  };
}

function normalizeFullNode(node, query) {
  const type = String(node?.type || node?.kind || '').toLowerCase();
  if (type === 'paper') return normalizePaperNode(node, query);
  if (type === 'domain') return normalizeDomainNode(node);
  if (type === 'seed') return buildQueryNode(query);
  return normalizeEntityNode(node, query);
}

function normalizeFullEdge(edge, index, nodeIds) {
  const source = String(edge?.source || '').trim();
  const target = String(edge?.target || '').trim();
  if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) return null;
  const relation = String(edge?.relation || 'related').trim() || 'related';
  const relevance = normalizeRate(edge?.weight ?? edge?.meta?.relevance ?? 0.32);
  return {
    id: String(edge?.id || `full-edge-${index}`),
    source,
    target,
    relation,
    kind: relation === 'seed_related' ? 'center' : 'peer',
    relevance,
    meta: edge?.meta || {}
  };
}

function buildFullGraph(nodesRaw, edgesRaw, query) {
  const nodes = nodesRaw.map((node) => normalizeFullNode(node, query));
  const nodeIds = new Set(nodes.map((node) => String(node?.id || '')).filter(Boolean));
  const edges = (edgesRaw || [])
    .map((edge, index) => normalizeFullEdge(edge, index, nodeIds))
    .filter(Boolean);

  const paperCount = nodes.filter((node) => node.kind === 'paper').length;
  const domainCount = nodes.filter((node) => node.kind === 'domain').length;
  const entityCount = nodes.filter((node) => node.kind === 'entity').length;

  return {
    key: 'full',
    title: '全量知识图谱',
    description: '展示后端构建的完整节点与关系网络。',
    centerNodeId: QUERY_NODE_ID,
    nodes,
    edges,
    counts: {
      seed: nodes.filter((node) => node.kind === 'seed').length,
      paper: paperCount,
      domain: domainCount,
      entity: entityCount,
      edges: edges.length
    }
  };
}

export function buildKnowledgeGraphSets(rawGraph) {
  const nodesRaw = Array.isArray(rawGraph?.nodes) ? rawGraph.nodes : [];
  const edgesRaw = Array.isArray(rawGraph?.edges) ? rawGraph.edges : [];
  const query = String(rawGraph?.query || '').trim();

  return {
    panorama: buildPanoramaGraph(nodesRaw, edgesRaw, query),
    full: buildFullGraph(nodesRaw, edgesRaw, query),
    paper: buildPaperGraph(nodesRaw, edgesRaw, query),
    domain: buildDomainGraph(nodesRaw, edgesRaw, query)
  };
}
