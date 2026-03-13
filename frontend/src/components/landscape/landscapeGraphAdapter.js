function slug(text) {
  return String(text || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'node';
}

function toNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function domainRelevance(direction) {
  const correlationScore = toNumber(direction?.correlation_score, NaN);
  if (Number.isFinite(correlationScore)) {
    return Math.max(0.08, Math.min(1, correlationScore));
  }
  const recentRatio = Math.max(0, Math.min(1, toNumber(direction?.recent_ratio, 0)));
  const avgCitations = toNumber(direction?.avg_citations, 0);
  const paperCount = toNumber(direction?.paper_count, 0);
  return Math.max(
    0.08,
    Math.min(recentRatio * 0.5 + Math.min(avgCitations / 600, 1) * 0.3 + Math.min(paperCount / 40, 1) * 0.2, 1)
  );
}

function paperRelevance(paper) {
  const citation = toNumber(paper?.citation_count, 0);
  const year = toNumber(paper?.year, 0);
  const citationScore = Math.min(citation / 2000, 1);
  const recencyBoost = year >= 2023 ? 0.15 : 0;
  return Math.max(0.12, Math.min(0.22 + citationScore * 0.72 + recencyBoost, 1));
}

export function buildLandscapeGraphFallback(landscape) {
  const domainName = String(landscape?.domain_name || landscape?.query || '领域').trim();
  const seedId = `seed:${slug(domainName)}`;

  const nodes = [
    {
      id: seedId,
      name: domainName,
      label: domainName,
      kind: 'seed',
      relevance: 1,
      score: 1,
      meta: {
        query: domainName,
        abstract: `${domainName} 领域知识图谱`
      }
    }
  ];
  const edges = [];

  const subDirections = Array.isArray(landscape?.sub_directions) ? landscape.sub_directions : [];
  for (let index = 0; index < subDirections.length; index += 1) {
    const direction = subDirections[index] || {};
    const directionName = String(direction?.name || '').trim();
    if (!directionName) continue;

    const directionId = `domain:${index}:${slug(directionName)}`;
    const relevance = domainRelevance(direction);
    const methods = Array.isArray(direction?.methods)
      ? direction.methods.map((item) => String(item || '').trim()).filter(Boolean)
      : [];
    const relatedPapers = Array.isArray(direction?.core_papers)
      ? direction.core_papers.map((paper) => ({
          id: String(paper?.id || '').trim(),
          title: String(paper?.title || '').trim(),
          year: toNumber(paper?.year, 0),
          citation_count: toNumber(paper?.citation_count, 0),
          authors: Array.isArray(paper?.authors) ? paper.authors.join(', ') : ''
        }))
      : [];

    nodes.push({
      id: directionId,
      name: directionName,
      label: directionName,
      kind: 'domain',
      relevance,
      score: relevance,
      meta: {
        paper_count: String(toNumber(direction?.paper_count, 0)),
        recent_ratio: String(Math.max(0, Math.min(1, toNumber(direction?.recent_ratio, 0))).toFixed(3)),
        avg_citations: String(toNumber(direction?.avg_citations, 0)),
        status: String(direction?.status || 'stable'),
        provider_used: String(direction?.provider_used || ''),
        description: String(direction?.description || ''),
        methods: methods.join('|'),
        related_papers: relatedPapers
      }
    });
    edges.push({
      id: `${seedId}->${directionId}`,
      source: seedId,
      target: directionId,
      kind: 'center',
      relevance,
      weight: relevance
    });

    const papers = relatedPapers.slice(0, 15);
    papers.forEach((paper, paperIndex) => {
      if (!paper.title) return;
      const rawPaperId = paper.id || `${directionId}:paper:${paperIndex}:${slug(paper.title)}`;
      const paperId = `paper:${rawPaperId}`;
      const relevanceScore = paperRelevance(paper);

      nodes.push({
        id: paperId,
        name: paper.title,
        label: paper.title,
        kind: 'paper',
        relevance: relevanceScore,
        score: relevanceScore,
        meta: {
          title: paper.title,
          year: String(toNumber(paper.year, 0)),
          published_month: '1',
          venue: 'Unknown Venue',
          authors: String(paper.authors || ''),
          abstract: `${directionName} 的代表论文`,
          citation_count: String(toNumber(paper.citation_count, 0)),
          relevance: relevanceScore.toFixed(3),
          keywords: String(direction?.description || '')
        }
      });
      edges.push({
        id: `${directionId}->${paperId}`,
        source: directionId,
        target: paperId,
        kind: 'related',
        relevance: Math.max(0.18, relevance * 0.82),
        weight: Math.max(0.18, relevance * 0.82)
      });
    });
  }

  return {
    title: `${domainName} 领域图谱`,
    nodes,
    edges,
    counts: {
      seed: 1,
      domain: nodes.filter((item) => item.kind === 'domain').length,
      paper: nodes.filter((item) => item.kind === 'paper').length,
      edges: edges.length
    }
  };
}
