import { clamp, normalizeRate, resolveNodeName } from './knowledgeGraphModel';

function parseSafeInt(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.round(parsed);
}

function parseSafeFloat(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return parsed;
}

function parseCitationCount(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.round(parsed));
}

function toAbstractSnippet(text) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  if (!value) return '暂无摘要信息。';
  return value.length > 300 ? `${value.slice(0, 297)}...` : value;
}

function formatPercent(rate) {
  return `${Math.round(normalizeRate(rate) * 100)}%`;
}

function formatYearMonth(yearValue, monthValue) {
  const year = parseSafeInt(yearValue, 0);
  if (year <= 0) return '--';
  const month = clamp(parseSafeInt(monthValue, 1), 1, 12);
  return `${String(year)}-${String(month).padStart(2, '0')}`;
}

function isRecentPaper(yearValue, monthValue) {
  const year = parseSafeInt(yearValue, 0);
  if (year <= 0) return false;
  const month = clamp(parseSafeInt(monthValue, 1), 1, 12);
  const now = new Date();
  const diffMonths = (now.getFullYear() - year) * 12 + (now.getMonth() + 1 - month);
  return diffMonths <= 36;
}

function compactTokens(text) {
  return String(text || '')
    .toLowerCase()
    .match(/[a-z0-9]{2,}/g) || [];
}

function toKeywords(raw, title, abstract) {
  const normalizedFromRaw = [];
  if (Array.isArray(raw)) {
    for (const item of raw) {
      const value = String(item || '').trim();
      if (value) normalizedFromRaw.push(value);
    }
  } else {
    const source = String(raw || '').trim();
    if (source) {
      const parts = source.split(/[|,]/g);
      for (const item of parts) {
        const value = item.trim();
        if (value) normalizedFromRaw.push(value);
      }
    }
  }

  const dedupRaw = [...new Set(normalizedFromRaw)].slice(0, 5);
  if (dedupRaw.length >= 3) return dedupRaw;

  const inferred = [...new Set(compactTokens(`${title} ${abstract}`))]
    .filter((token) => token.length >= 4)
    .filter((token) => !['using', 'based', 'approach', 'method', 'results', 'paper'].includes(token))
    .slice(0, 5)
    .map((token) => token[0].toUpperCase() + token.slice(1));

  const merged = [...dedupRaw, ...inferred].slice(0, 5);
  while (merged.length < 3) {
    merged.push(['Research', 'Model', 'Evidence', 'Analysis'][merged.length]);
  }
  return merged;
}

function toAuthorVenue(authors, venue) {
  const authorText = String(authors || '').trim();
  const venueText = String(venue || '').trim();
  const parts = [authorText, venueText].filter(Boolean);
  return parts.join(' · ') || '作者与来源未知';
}

function toImpactFactorInfo(meta, influenceRate) {
  const rawIf = parseSafeFloat(meta?.impact_factor, NaN);
  if (Number.isFinite(rawIf) && rawIf > 0) {
    return {
      text: `IF ${rawIf.toFixed(1)}`,
      quartile: String(meta?.quartile || '--')
    };
  }

  const proxy = clamp(1.2 + influenceRate * 14, 1.2, 15.8);
  const quartile = proxy >= 10 ? 'Q1' : proxy >= 6 ? 'Q2' : proxy >= 3 ? 'Q3' : 'Q4';
  return {
    text: `IF ${proxy.toFixed(1)}`,
    quartile
  };
}

function resolveDomainKeywords(nodeName, relatedPapers) {
  if (relatedPapers.length) {
    return relatedPapers.slice(0, 5).map((paper) => paper.title || paper.name).filter(Boolean);
  }
  const inferred = compactTokens(nodeName).slice(0, 3).map((token) => token[0].toUpperCase() + token.slice(1));
  return inferred.length ? inferred : ['Domain', 'Research', 'Topic'];
}

function toPercentText(value) {
  const ratio = clamp(parseSafeFloat(value, 0), 0, 1);
  return `${Math.round(ratio * 100)}%`;
}

function splitPipeText(value) {
  const raw = String(value || '').trim();
  if (!raw) return [];
  return raw
    .split('|')
    .map((item) => item.trim())
    .filter(Boolean);
}

function statusText(value) {
  const key = String(value || '').toLowerCase();
  if (key === 'emerging') return '新兴';
  if (key === 'growing') return '爆发';
  if (key === 'saturated') return '饱和';
  return '成熟';
}

function buildPaperDetail(node) {
  const name = resolveNodeName(node);
  const relevance = normalizeRate(node?.relevance ?? node?.meta?.relevance ?? 0);
  const influence = normalizeRate(node?.meta?.influence ?? node?.score);
  const citationCount = parseCitationCount(node?.meta?.citation_count);
  const publicationYear = parseSafeInt(node?.meta?.year, 0);
  const publicationMonth = parseSafeInt(node?.meta?.published_month, 1);
  const publishedAt = formatYearMonth(publicationYear, publicationMonth);
  const recent = isRecentPaper(publicationYear, publicationMonth);
  const impactFactorInfo = toImpactFactorInfo(node?.meta, influence);
  const keywords = toKeywords(node?.meta?.keywords, name, node?.meta?.abstract || '');
  const isCitationHot = citationCount >= 1000;

  return {
    id: node.id,
    name,
    isPaper: true,
    isDomain: false,
    isSeed: false,
    typeLabel: '论文节点',
    relevance,
    relevanceText: relevance.toFixed(2),
    relevancePercentText: formatPercent(relevance),
    relevanceBarWidth: `${Math.round(relevance * 100)}%`,
    relevanceToneClass: relevance >= 0.85 ? 'is-high' : relevance < 0.45 ? 'is-low' : 'is-mid',
    authorVenueText: toAuthorVenue(node?.meta?.authors, node?.meta?.venue),
    abstractSnippet: toAbstractSnippet(node?.meta?.abstract),
    keywords,
    publishedAtText: publishedAt,
    publishedStatusText: recent ? 'Recent' : '较早',
    publishedStatusClass: recent ? 'is-recent' : 'is-older',
    impactFactorText: impactFactorInfo.text,
    quartileText: impactFactorInfo.quartile,
    citationCountText: citationCount.toLocaleString(),
    citationHotClass: isCitationHot ? 'is-hot' : '',
    url: String(node?.meta?.url || '').trim()
  };
}

function buildDomainDetail(node) {
  const name = resolveNodeName(node);
  const relevance = normalizeRate(node?.relevance ?? node?.meta?.relevance ?? node?.score);
  const relatedPapers = Array.isArray(node?.meta?.related_papers) ? node.meta.related_papers : [];
  const paperCount = parseSafeInt(node?.meta?.paper_count, relatedPapers.length);
  const keywords = resolveDomainKeywords(name, relatedPapers);
  const methods = splitPipeText(node?.meta?.methods);
  const recentRatio = clamp(parseSafeFloat(node?.meta?.recent_ratio, 0), 0, 1);
  const avgCitations = parseSafeInt(node?.meta?.avg_citations, 0);
  const provider = String(node?.meta?.provider_used || '').trim() || 'none';
  const domainCorePapers = relatedPapers.slice(0, 3).map((paper) => ({
    title: String(paper?.title || '').trim(),
    year: parseSafeInt(paper?.year, 0),
    citationCount: parseSafeInt(paper?.citation_count, 0)
  })).filter((paper) => paper.title);

  return {
    id: node.id,
    name,
    isPaper: false,
    isDomain: true,
    isSeed: false,
    typeLabel: '领域节点',
    relevance,
    relevanceText: relevance.toFixed(2),
    relevancePercentText: formatPercent(relevance),
    relevanceBarWidth: `${Math.round(relevance * 100)}%`,
    relevanceToneClass: relevance >= 0.75 ? 'is-high' : relevance < 0.4 ? 'is-low' : 'is-mid',
    authorVenueText: `领域覆盖 ${paperCount} 篇论文`,
    abstractSnippet: `该领域与输入论文的关联度为 ${formatPercent(relevance)}。`,
    keywords,
    domainStatusText: statusText(node?.meta?.status),
    domainRecentRatioText: toPercentText(recentRatio),
    domainAvgCitationsText: avgCitations.toLocaleString(),
    domainProviderText: provider,
    domainMethods: methods,
    domainCorePapers,
    domainPaperCountText: String(paperCount),
    domainTopPaperText: relatedPapers[0]?.title || '暂无代表论文',
    domainRelatedPapers: relatedPapers
  };
}

function buildSeedDetail(node) {
  const query = String(node?.meta?.query || node?.label || '').trim();
  const name = query || '中心论文';
  return {
    id: node.id,
    name,
    isPaper: false,
    isDomain: false,
    isSeed: true,
    typeLabel: '中心节点',
    relevance: 1,
    relevanceText: '1.00',
    relevancePercentText: '100%',
    relevanceBarWidth: '100%',
    relevanceToneClass: 'is-high',
    authorVenueText: '中心论文',
    abstractSnippet: '该节点表示本次分析的中心论文，图中其他节点围绕它展示关联程度。',
    keywords: toKeywords('', query, '')
  };
}

export function buildKnowledgeNodeDetail(node) {
  if (!node) return null;
  if (node.kind === 'paper' || node.type === 'paper') return buildPaperDetail(node);
  if (node.kind === 'domain' || node.type === 'domain') return buildDomainDetail(node);
  return buildSeedDetail(node);
}
