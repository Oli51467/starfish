function toSafeNodeId(value) {
  return String(value || '').trim();
}

export function buildDomainEdgeTopology(nodesRaw, edgesRaw) {
  const nodeKindById = new Map();
  for (const node of nodesRaw || []) {
    const nodeId = toSafeNodeId(node?.id);
    if (!nodeId) continue;
    const nodeKind = String(node?.kind || node?.type || '').trim().toLowerCase();
    nodeKindById.set(nodeId, nodeKind);
  }

  const paperDomainById = new Map();
  const domainPaperIdsById = new Map();
  const domainEntityIdsById = new Map();

  for (const edge of edgesRaw || []) {
    const sourceId = toSafeNodeId(edge?.source);
    const targetId = toSafeNodeId(edge?.target);
    if (!sourceId || !targetId) continue;
    const sourceKind = nodeKindById.get(sourceId);
    const targetKind = nodeKindById.get(targetId);
    const relation = String(edge?.relation || '').trim().toLowerCase();

    const sourceIsDomain = sourceKind === 'domain';
    const targetIsDomain = targetKind === 'domain';
    const sourceIsPaper = sourceKind === 'paper';
    const targetIsPaper = targetKind === 'paper';
    const sourceIsEntity = sourceKind === 'entity';
    const targetIsEntity = targetKind === 'entity';

    if (
      relation === 'belongs_to'
      || (sourceIsDomain && targetIsPaper)
      || (sourceIsPaper && targetIsDomain)
      || relation === 'domain_paper'
    ) {
      const domainId = sourceIsDomain ? sourceId : (targetIsDomain ? targetId : '');
      const paperId = sourceIsPaper ? sourceId : (targetIsPaper ? targetId : '');
      if (domainId && paperId) {
        paperDomainById.set(paperId, domainId);
        const paperSet = domainPaperIdsById.get(domainId) || new Set();
        paperSet.add(paperId);
        domainPaperIdsById.set(domainId, paperSet);
      }
      continue;
    }

    if (
      relation === 'covers'
      || relation === 'domain_entity'
      || (sourceIsDomain && targetIsEntity)
      || (sourceIsEntity && targetIsDomain)
    ) {
      const domainId = sourceIsDomain ? sourceId : (targetIsDomain ? targetId : '');
      const entityId = sourceIsEntity ? sourceId : (targetIsEntity ? targetId : '');
      if (domainId && entityId) {
        const entitySet = domainEntityIdsById.get(domainId) || new Set();
        entitySet.add(entityId);
        domainEntityIdsById.set(domainId, entitySet);
      }
    }
  }

  return {
    nodeKindById,
    paperDomainById,
    domainPaperIdsById,
    domainEntityIdsById
  };
}

export function resolveDomainNodeIds(topology, domainId, options = {}) {
  const includeEntities = options?.includeEntities !== false;
  const safeDomainId = toSafeNodeId(domainId);
  if (!topology || !safeDomainId) return new Set();

  const nodeIds = new Set([safeDomainId]);
  const paperIds = topology.domainPaperIdsById?.get(safeDomainId) || new Set();
  for (const paperId of paperIds) nodeIds.add(paperId);

  if (includeEntities) {
    const entityIds = topology.domainEntityIdsById?.get(safeDomainId) || new Set();
    for (const entityId of entityIds) nodeIds.add(entityId);
  }
  return nodeIds;
}
