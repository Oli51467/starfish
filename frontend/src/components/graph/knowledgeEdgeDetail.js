import { normalizeRate, resolveNodeName } from './knowledgeGraphModel';

const EDGE_RELATION_LABEL_MAP = Object.freeze({
  related: '论文关联',
  peer_related: '论文关联',
  seed_related: '种子关联',
  mentions: '论文提及',
  belongs_to: '方向归属',
  covers: '方向覆盖'
});

function resolveNodeKind(node) {
  return String(node?.kind || node?.type || '').trim().toLowerCase();
}

function parseSafeInt(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.round(parsed));
}

function splitSharedEntities(rawValue, limit = 6) {
  const safeLimit = Math.max(1, Number(limit) || 6);
  const source = String(rawValue || '').trim();
  if (!source) return [];

  const deduped = [];
  const seen = new Set();
  for (const token of source.split(/[,\n|]/g)) {
    const value = token.trim();
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(value);
    if (deduped.length >= safeLimit) break;
  }
  return deduped;
}

function resolveNodeUrl(node) {
  return String(node?.meta?.url || node?.url || '').trim();
}

function resolvePaperMeta(node) {
  const year = parseSafeInt(node?.meta?.year);
  const citationCount = parseSafeInt(node?.meta?.citation_count);
  return {
    yearText: year > 0 ? String(year) : '--',
    citationText: citationCount > 0 ? `${citationCount.toLocaleString()} 引` : '引文待补充'
  };
}

function resolveRelationKey(edge) {
  return String(edge?.relation || edge?.kind || '').trim().toLowerCase() || 'related';
}

function resolveRelationText(relationKey) {
  return EDGE_RELATION_LABEL_MAP[relationKey] || '节点关系';
}

function resolveStrengthRate(edge) {
  const rawValue = Number(edge?.relevance ?? edge?.weight ?? edge?.meta?.relevance);
  if (!Number.isFinite(rawValue)) return 0;
  return normalizeRate(rawValue);
}

function buildSummaryText({
  relationKey,
  sourceName,
  targetName,
  sharedEntities,
  relationLabel
}) {
  const safeSource = String(sourceName || '').trim() || '源节点';
  const safeTarget = String(targetName || '').trim() || '目标节点';
  if (sharedEntities.length) {
    return `两篇论文在 ${sharedEntities.slice(0, 3).join('、')} 等主题上存在明显交集。`;
  }
  if (relationLabel) return relationLabel;
  if (relationKey === 'peer_related' || relationKey === 'related') {
    return `${safeSource} 与 ${safeTarget} 在语义与主题上具备较高关联。`;
  }
  if (relationKey === 'seed_related') {
    return `${safeSource} 与种子主题存在直接关联。`;
  }
  if (relationKey === 'belongs_to') {
    return `${safeSource} 归属于 ${safeTarget} 方向。`;
  }
  return `${safeSource} 与 ${safeTarget} 存在结构化关联。`;
}

export function buildKnowledgeEdgeDetail(edge, nodeById) {
  if (!edge || !(nodeById instanceof Map)) return null;

  const sourceId = String(edge?.source || '').trim();
  const targetId = String(edge?.target || '').trim();
  if (!sourceId || !targetId) return null;

  const sourceNode = nodeById.get(sourceId);
  const targetNode = nodeById.get(targetId);
  if (!sourceNode || !targetNode) return null;

  const sourceKind = resolveNodeKind(sourceNode);
  const targetKind = resolveNodeKind(targetNode);
  const sourceName = resolveNodeName(sourceNode);
  const targetName = resolveNodeName(targetNode);
  const sourcePaperMeta = resolvePaperMeta(sourceNode);
  const targetPaperMeta = resolvePaperMeta(targetNode);
  const relationKey = resolveRelationKey(edge);
  const relationText = resolveRelationText(relationKey);
  const strengthRate = resolveStrengthRate(edge);
  const relationLabel = String(edge?.meta?.relation_label || edge?.meta?.relationLabel || '').trim();
  const sharedEntities = splitSharedEntities(edge?.meta?.shared_entities || edge?.meta?.sharedEntities || '');

  return {
    id: String(edge?.id || '').trim() || `${sourceId}->${targetId}`,
    sourceId,
    targetId,
    relationKey,
    relationText,
    strengthRate,
    strengthPercentText: `${Math.round(strengthRate * 100)}%`,
    strengthBarWidth: `${Math.round(strengthRate * 100)}%`,
    isPaperPair: sourceKind === 'paper' && targetKind === 'paper',
    source: {
      id: sourceId,
      kind: sourceKind,
      name: sourceName,
      url: resolveNodeUrl(sourceNode),
      yearText: sourcePaperMeta.yearText,
      citationText: sourcePaperMeta.citationText
    },
    target: {
      id: targetId,
      kind: targetKind,
      name: targetName,
      url: resolveNodeUrl(targetNode),
      yearText: targetPaperMeta.yearText,
      citationText: targetPaperMeta.citationText
    },
    sharedEntities,
    summaryText: buildSummaryText({
      relationKey,
      sourceName,
      targetName,
      sharedEntities,
      relationLabel
    })
  };
}
