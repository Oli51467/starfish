function safeRate(rawValue, fallback = 0) {
  const parsed = Number(rawValue);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(parsed, 1));
}

export function adaptDomainGraphFromHistoryGraph(graph, fallbackQuery = '') {
  const rawNodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const rawEdges = Array.isArray(graph?.edges) ? graph.edges : [];
  const query = String(graph?.query || fallbackQuery || '').trim();

  const nodes = rawNodes
    .map((node) => {
      const id = String(node?.id || '').trim();
      if (!id) return null;
      let kind = 'paper';
      if (id.startsWith('seed:')) kind = 'seed';
      else if (String(node?.type || '').toLowerCase() === 'domain') kind = 'domain';
      else if (String(node?.type || '').toLowerCase() === 'paper') kind = 'paper';
      else return null;

      const label = String(node?.label || id).trim() || id;
      const score = safeRate(node?.score, 0);
      const relevance = safeRate(node?.meta?.relevance, score);
      const size = Math.max(1, Number(node?.size) || 1);
      return {
        id,
        name: label,
        label,
        kind,
        relevance,
        score,
        size,
        meta: node?.meta && typeof node.meta === 'object' ? { ...node.meta } : {}
      };
    })
    .filter(Boolean);

  const edges = rawEdges
    .map((edge, index) => {
      const source = String(edge?.source || '').trim();
      const target = String(edge?.target || '').trim();
      if (!source || !target) return null;
      const relation = String(edge?.relation || '').toLowerCase();
      const kind = relation === 'covers' ? 'center' : 'related';
      const relevance = safeRate(edge?.weight, 0.25);
      return {
        id: `history-edge-${index}`,
        source,
        target,
        kind,
        relevance,
        weight: relevance,
        meta: edge?.meta && typeof edge.meta === 'object' ? { ...edge.meta } : {}
      };
    })
    .filter(Boolean);

  return {
    title: `${query || '领域研究'} 领域图谱`,
    query,
    nodes,
    edges,
    counts: {
      seed: nodes.filter((item) => item.kind === 'seed').length,
      domain: nodes.filter((item) => item.kind === 'domain').length,
      paper: nodes.filter((item) => item.kind === 'paper').length,
      edges: edges.length
    }
  };
}
