<template>
  <div class="knowledge-graph-body knowledge-graph-body-full">
    <div ref="graphContainerRef" class="knowledge-graph-canvas" role="img" :aria-label="graphAriaLabel"></div>

    <div class="knowledge-legend-overlay">
      <div class="legend-row">
        <span class="legend-dot node-seed"></span>中心论文（{{ counts.seed }}）
      </div>
      <div v-if="counts.paper" class="legend-row">
        <span class="legend-dot node-paper"></span>论文（{{ counts.paper }}）
      </div>
      <div v-if="counts.domain" class="legend-row">
        <span class="legend-dot node-domain"></span>领域（{{ counts.domain }}）
      </div>
      <div class="legend-row">
        <span class="legend-line edge-generic"></span>关联边（{{ counts.edges }}）
      </div>
    </div>

    <article
      v-if="pinnedNodeDetail"
      ref="cardOverlayRef"
      class="knowledge-node-card-overlay"
      :style="pinnedCardStyle"
    >
      <header class="paper-node-card-top">
        <div class="paper-node-title-wrap">
          <p class="paper-node-title">{{ pinnedNodeDetail.name }}</p>
          <p class="paper-node-subtitle">{{ pinnedNodeDetail.authorVenueText }}</p>
        </div>
        <div class="paper-node-top-right">
          <p class="paper-node-relevance-pill" :class="pinnedNodeDetail.relevanceToneClass">
            <span>RELEVANCE</span>
            <strong>{{ pinnedNodeDetail.relevancePercentText }}</strong>
          </p>
          <button
            class="knowledge-node-card-close"
            type="button"
            aria-label="关闭卡片"
            title="关闭"
            @click="closePinnedCard"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>
      </header>

      <section class="paper-node-middle">
        <p class="paper-node-abstract">{{ pinnedNodeDetail.abstractSnippet }}</p>
        <div class="paper-node-keywords">
          <span v-for="keyword in pinnedNodeDetail.keywords" :key="keyword" class="paper-node-keyword-chip">
            {{ keyword }}
          </span>
        </div>
      </section>

      <section v-if="pinnedNodeDetail.isPaper" class="paper-node-metrics-grid">
        <article class="paper-node-metric" :class="pinnedNodeDetail.relevanceToneClass">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">相关度</p>
          </div>
          <p class="paper-node-metric-value accent">{{ pinnedNodeDetail.relevancePercentText }}</p>
          <div class="paper-node-progress-track">
            <span class="paper-node-progress-fill" :style="{ width: pinnedNodeDetail.relevanceBarWidth }"></span>
          </div>
        </article>

        <article class="paper-node-metric">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">发布时间</p>
            <span class="paper-node-status-chip" :class="pinnedNodeDetail.publishedStatusClass">
              {{ pinnedNodeDetail.publishedStatusText }}
            </span>
          </div>
          <p class="paper-node-metric-value">{{ pinnedNodeDetail.publishedAtText }}</p>
        </article>

        <article class="paper-node-metric">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">影响因子</p>
            <span class="paper-node-status-chip">{{ pinnedNodeDetail.quartileText }}</span>
          </div>
          <p class="paper-node-metric-value">{{ pinnedNodeDetail.impactFactorText }}</p>
        </article>

        <article class="paper-node-metric">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">引用数</p>
          </div>
          <p class="paper-node-metric-value" :class="pinnedNodeDetail.citationHotClass">
            {{ pinnedNodeDetail.citationCountText }}
          </p>
        </article>
      </section>

      <section v-else-if="pinnedNodeDetail.isDomain" class="paper-node-metrics-grid paper-node-metrics-grid-domain">
        <article class="paper-node-metric" :class="pinnedNodeDetail.relevanceToneClass">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">相关度</p>
          </div>
          <p class="paper-node-metric-value accent">{{ pinnedNodeDetail.relevancePercentText }}</p>
          <div class="paper-node-progress-track">
            <span class="paper-node-progress-fill" :style="{ width: pinnedNodeDetail.relevanceBarWidth }"></span>
          </div>
        </article>

        <article class="paper-node-metric">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">关联论文</p>
          </div>
          <p class="paper-node-metric-value">{{ pinnedNodeDetail.domainPaperCountText }}</p>
        </article>

        <article class="paper-node-metric paper-node-metric-wide">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">代表论文</p>
          </div>
          <p class="paper-node-metric-value">{{ pinnedNodeDetail.domainTopPaperText }}</p>
        </article>
      </section>

      <section v-else class="paper-node-metrics-grid paper-node-metrics-grid-seed">
        <article class="paper-node-metric">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">中心节点</p>
          </div>
          <p class="paper-node-metric-value">中心论文</p>
        </article>
      </section>

      <footer v-if="pinnedNodeDetail.isPaper" class="paper-node-actions">
        <a
          v-if="pinnedNodeDetail.url"
          class="paper-node-action-btn"
          :href="pinnedNodeDetail.url"
          target="_blank"
          rel="noreferrer noopener"
        >
          查看详情
        </a>
        <button class="paper-node-action-btn" type="button" @click="exportCitation">
          导出引用
        </button>
        <button class="paper-node-action-btn" type="button" @click="toggleBookmark">
          {{ pinnedNodeDetail.isBookmarked ? '已收藏' : '收藏' }}
        </button>
      </footer>
    </article>
  </div>
</template>

<script setup>
import { Graph } from '@antv/g6';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { buildKnowledgeNodeDetail } from './knowledgeNodeDetail';
import { clamp, normalizeRate, shortLabel } from './knowledgeGraphModel';

const props = defineProps({
  graph: {
    type: Object,
    required: true
  }
});

const graphContainerRef = ref(null);
const pinnedNode = ref(null);
const pinnedCardPoint = ref(null);
const cardOverlayRef = ref(null);
const pinnedCardSize = ref({ width: 460, height: 300 });
const bookmarkedNodeIds = ref([]);
let graphInstance = null;
let resizeObserver = null;
let resizeRaf = 0;
let nodeClickHandler = null;

const NODE_STYLE = {
  seed: {
    fill: '#eaf3ff',
    stroke: '#87a8d2'
  },
  domain: {
    fill: '#f5f8fd',
    stroke: '#4d709c'
  }
};

const PAPER_PALETTE = [
  { fill: '#f9f4ea', stroke: '#9b835d' },
  { fill: '#f4f8ee', stroke: '#6e9157' },
  { fill: '#eef7f8', stroke: '#4f8c8d' },
  { fill: '#f3f2f9', stroke: '#74719c' },
  { fill: '#f8f1f2', stroke: '#9c6771' },
  { fill: '#f2f6fc', stroke: '#5f7ea3' },
  { fill: '#f7f5ef', stroke: '#8f805b' },
  { fill: '#f0f6f2', stroke: '#5f8d71' }
];

function hashText(value) {
  const input = String(value || '');
  let hash = 0;
  for (let index = 0; index < input.length; index += 1) {
    hash = (hash << 5) - hash + input.charCodeAt(index);
    hash |= 0;
  }
  return Math.abs(hash);
}

function resolveNodePalette(node) {
  const kind = node?.kind || node?.type || 'paper';
  if (kind === 'paper') {
    const paletteIndex = hashText(node?.id || node?.label || '') % PAPER_PALETTE.length;
    return PAPER_PALETTE[paletteIndex];
  }
  return NODE_STYLE[kind] || NODE_STYLE.domain;
}

function edgeStroke(relevance, kind) {
  const normalized = normalizeRate(relevance);
  const base = kind === 'center' ? 0.28 : 0.18;
  const boost = kind === 'center' ? 0.62 : 0.5;
  const alpha = clamp(base + normalized * boost, 0.16, 0.9);
  return `rgba(76, 175, 80, ${alpha.toFixed(3)})`;
}

function edgeWidth(relevance, kind) {
  const normalized = normalizeRate(relevance);
  const base = kind === 'center' ? 0.9 : 0.7;
  const boost = kind === 'center' ? 1.95 : 1.3;
  return clamp(base + normalized * boost, 0.6, 2.85);
}

function edgeDistance(relevance, kind) {
  const normalized = normalizeRate(relevance);
  if (kind === 'center') {
    return clamp(306 - normalized * 198, 98, 306);
  }
  return clamp(338 - normalized * 116, 178, 338);
}

function nodeSize(node, totalNodes) {
  const normalized = normalizeRate(node?.relevance ?? node?.score);
  if (node?.kind === 'seed') {
    return clamp(30 + totalNodes * 0.1, 28, 38);
  }
  if (node?.kind === 'domain') {
    return clamp(15 + normalized * 12, 14, 27);
  }
  return clamp(14 + normalized * 11, 13, 25);
}

function getContainerSize() {
  const container = graphContainerRef.value;
  const width = Math.max(320, Math.floor(container?.clientWidth || 920));
  const height = Math.max(260, Math.floor(container?.clientHeight || 560));
  return { width, height };
}

function toG6Data(graphPayload) {
  const nodesRaw = graphPayload?.nodes || [];
  const edgesRaw = graphPayload?.edges || [];
  const totalNodes = Math.max(1, nodesRaw.length);
  const edgeLabelEnabled = edgesRaw.length <= 45;

  const nodes = nodesRaw.map((node) => {
    const kind = node.kind || node.type || 'paper';
    const palette = resolveNodePalette(node);
    const size = nodeSize(node, totalNodes);
    const labelText = shortLabel(node.name || node.label, 22);
    return {
      id: node.id,
      data: {
        ...node,
        nodeKind: kind,
        resolvedSize: size
      },
      style: {
        size,
        fill: palette.fill,
        stroke: palette.stroke,
        lineWidth: kind === 'seed' ? 1.6 : 1.25,
        shadowBlur: 4,
        shadowColor: 'rgba(0, 0, 0, 0.04)',
        label: true,
        labelText,
        labelPlacement: 'bottom',
        labelOffsetY: 6,
        labelFontSize: totalNodes > 26 ? 9 : 10,
        labelFill: '#2f2f2f',
        labelBackground: false,
        cursor: 'pointer'
      }
    };
  });

  const edges = edgesRaw.map((edge, index) => {
    const kind = edge?.kind || 'center';
    const relevance = normalizeRate(edge?.relevance ?? edge?.weight);
    return {
      id: edge.id || `edge-${index}`,
      source: String(edge?.source || ''),
      target: String(edge?.target || ''),
      data: {
        ...edge,
        kind,
        relevance
      },
      style: {
        stroke: edgeStroke(relevance, kind),
        lineWidth: edgeWidth(relevance, kind),
        strokeOpacity: 1,
        endArrow: false,
        lineDash: relevance < 0.35 ? [5, 4] : undefined,
        label: edgeLabelEnabled && kind === 'center',
        labelText: `${Math.round(relevance * 100)}%`,
        labelPlacement: 'center',
        labelFill: '#4e7d52',
        labelFontSize: 9,
        labelBackground: true,
        labelBackgroundFill: 'rgba(255, 255, 255, 0.92)',
        labelBackgroundRadius: 3,
        labelBackgroundPadding: [2, 4]
      }
    };
  });

  return { nodes, edges };
}

function buildLayout(width, height, totalNodes, edgeCount) {
  const crowdFactor = clamp(edgeCount / Math.max(1, totalNodes), 1.2, 6.2);
  return {
    type: 'd3-force',
    animation: true,
    preventOverlap: true,
    center: [width / 2, height / 2],
    alphaDecay: 0.08,
    velocityDecay: 0.4,
    iterations: 240,
    manyBody: {
      strength: -520 - crowdFactor * 52,
      distanceMax: 1050
    },
    link: {
      distance: (edge) => edgeDistance(edge?.data?.relevance, edge?.data?.kind),
      strength: (edge) => {
        const normalized = normalizeRate(edge?.data?.relevance);
        if (edge?.data?.kind === 'center') {
          return clamp(0.52 + normalized * 0.34, 0.52, 0.9);
        }
        return clamp(0.18 + normalized * 0.28, 0.18, 0.5);
      }
    },
    collide: {
      strength: 0.88,
      iterations: 5,
      radius: (node) => Number(node?.data?.resolvedSize || 11) / 2 + 16
    }
  };
}

function graphOptions(width, height) {
  const data = toG6Data(props.graph);
  return {
    width,
    height,
    autoFit: 'view',
    padding: 20,
    data,
    layout: buildLayout(width, height, data.nodes.length, data.edges.length),
    node: {
      type: 'circle'
    },
    edge: {
      type: 'line'
    },
    behaviors: [
      { type: 'drag-element-force' },
      { type: 'zoom-canvas' },
      { type: 'drag-canvas' },
      { type: 'hover-activate' }
    ]
  };
}

function resolveEventNodeId(event) {
  const candidates = [
    event?.target?.id,
    event?.target?.config?.id,
    event?.target?.attributes?.id,
    event?.item?.id,
    event?.itemID,
    event?.id,
    event?.data?.id
  ];
  const knownIds = new Set((props.graph?.nodes || []).map((node) => node.id));

  for (const candidate of candidates) {
    const value = String(candidate || '').trim();
    if (!value) continue;
    if (knownIds.has(value)) return value;
    for (const knownId of knownIds) {
      if (value.includes(knownId)) return knownId;
    }
  }
  return '';
}

function resolveEventPoint(event) {
  const rect = graphContainerRef.value?.getBoundingClientRect();
  const clientX = Number(event?.client?.x ?? event?.originalEvent?.clientX ?? event?.srcEvent?.clientX ?? NaN);
  const clientY = Number(event?.client?.y ?? event?.originalEvent?.clientY ?? event?.srcEvent?.clientY ?? NaN);
  if (rect && Number.isFinite(clientX) && Number.isFinite(clientY)) {
    return {
      x: clientX - rect.left,
      y: clientY - rect.top
    };
  }

  const directX = Number(event?.canvas?.x ?? event?.canvasX ?? event?.x ?? event?.position?.x ?? NaN);
  const directY = Number(event?.canvas?.y ?? event?.canvasY ?? event?.y ?? event?.position?.y ?? NaN);
  if (Number.isFinite(directX) && Number.isFinite(directY)) {
    return { x: directX, y: directY };
  }
  return null;
}

function normalizePoint(value) {
  if (Array.isArray(value) && value.length >= 2) {
    const x = Number(value[0]);
    const y = Number(value[1]);
    if (Number.isFinite(x) && Number.isFinite(y)) return { x, y };
  }
  const x = Number(value?.x);
  const y = Number(value?.y);
  if (Number.isFinite(x) && Number.isFinite(y)) return { x, y };
  return null;
}

function bindNodeClick() {
  if (!graphInstance || nodeClickHandler) return;

  nodeClickHandler = (event) => {
    const nodeId = resolveEventNodeId(event);
    if (!nodeId) return;
    const node = (props.graph?.nodes || []).find((item) => item.id === nodeId);
    if (!node) return;

    pinnedNode.value = node;
    let point = resolveEventPoint(event);
    if (!point && graphInstance?.getElementPosition) {
      try {
        point = normalizePoint(graphInstance.getElementPosition(nodeId));
      } catch {
        point = null;
      }
    }
    if (point) pinnedCardPoint.value = point;
  };

  graphInstance.on('node:click', nodeClickHandler);
  graphInstance.on('node:pointertap', nodeClickHandler);
}

function unbindNodeClick() {
  if (!graphInstance || !nodeClickHandler) return;
  graphInstance.off('node:click', nodeClickHandler);
  graphInstance.off('node:pointertap', nodeClickHandler);
  nodeClickHandler = null;
}

async function initGraph() {
  if (!graphContainerRef.value || graphInstance) return;
  const { width, height } = getContainerSize();

  graphInstance = new Graph({
    container: graphContainerRef.value,
    ...graphOptions(width, height)
  });

  await graphInstance.render();
  bindNodeClick();
}

async function updateGraphData() {
  if (!graphInstance) {
    await initGraph();
    return;
  }
  const { width, height } = getContainerSize();
  graphInstance.setOptions(graphOptions(width, height));
  await graphInstance.render();
}

async function refreshGraphDisplay() {
  closePinnedCard();
  await updateGraphData();
  if (graphInstance?.fitView) {
    try {
      graphInstance.fitView();
    } catch {
      // no-op
    }
  }
}

function setupResizeObserver() {
  if (!graphContainerRef.value) return;
  resizeObserver = new ResizeObserver(() => {
    if (resizeRaf) cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(async () => {
      resizeRaf = 0;
      if (!graphInstance) return;
      const { width, height } = getContainerSize();
      graphInstance.resize(width, height);
      graphInstance.setOptions(graphOptions(width, height));
      await graphInstance.render();
    });
  });
  resizeObserver.observe(graphContainerRef.value);
}

function closePinnedCard() {
  pinnedNode.value = null;
  pinnedCardPoint.value = null;
}

function exportCitation() {
  const detail = pinnedNodeDetail.value;
  if (!detail || !detail.isPaper) return;
  const citationText = `${detail.name}. ${detail.authorVenueText}. ${detail.publishedAtText}.`;
  if (navigator?.clipboard?.writeText) {
    navigator.clipboard.writeText(citationText).catch(() => {});
  }
}

function toggleBookmark() {
  const detail = pinnedNodeDetail.value;
  if (!detail || !detail.isPaper) return;
  const next = [...bookmarkedNodeIds.value];
  const index = next.indexOf(detail.id);
  if (index >= 0) {
    next.splice(index, 1);
  } else {
    next.push(detail.id);
  }
  bookmarkedNodeIds.value = next;
}

const graphAriaLabel = computed(() => `${props.graph?.title || '知识图谱'}可视化`);

const counts = computed(() => {
  const fromGraph = props.graph?.counts;
  if (fromGraph) {
    return {
      seed: Number(fromGraph.seed || 1),
      paper: Number(fromGraph.paper || 0),
      domain: Number(fromGraph.domain || 0),
      edges: Number(fromGraph.edges || 0)
    };
  }
  const nodes = props.graph?.nodes || [];
  const edges = props.graph?.edges || [];
  return {
    seed: nodes.filter((node) => node.kind === 'seed').length,
    paper: nodes.filter((node) => node.kind === 'paper').length,
    domain: nodes.filter((node) => node.kind === 'domain').length,
    edges: edges.length
  };
});

const pinnedNodeDetail = computed(() => {
  const detail = buildKnowledgeNodeDetail(pinnedNode.value);
  if (!detail) return null;
  return {
    ...detail,
    isBookmarked: bookmarkedNodeIds.value.includes(detail.id)
  };
});

const pinnedCardStyle = computed(() => {
  const point = pinnedCardPoint.value;
  const width = graphContainerRef.value?.clientWidth || 920;
  const height = graphContainerRef.value?.clientHeight || 560;
  const measuredWidth = Number(cardOverlayRef.value?.offsetWidth || pinnedCardSize.value.width || 0);
  const measuredHeight = Number(cardOverlayRef.value?.offsetHeight || pinnedCardSize.value.height || 0);
  const cardWidth = clamp(measuredWidth || 420, 320, Math.max(320, width - 24));
  const cardHeight = clamp(measuredHeight || 300, 220, Math.max(220, height - 20));
  const horizontalGap = 18;
  const topInset = 10;
  const leftInset = 12;

  if (!point) {
    return {
      left: `${leftInset}px`,
      top: `${topInset}px`,
      width: `${Math.round(cardWidth)}px`
    };
  }

  const canPlaceRight = point.x + horizontalGap + cardWidth <= width - leftInset;
  const canPlaceLeft = point.x - horizontalGap - cardWidth >= leftInset;
  const leftCandidate = canPlaceRight || !canPlaceLeft
    ? point.x + horizontalGap
    : point.x - cardWidth - horizontalGap;
  const topCandidate = point.y - cardHeight * 0.35;

  return {
    left: `${clamp(leftCandidate, leftInset, Math.max(leftInset, width - cardWidth - leftInset))}px`,
    top: `${clamp(topCandidate, topInset, Math.max(topInset, height - cardHeight - topInset))}px`,
    width: `${Math.round(cardWidth)}px`
  };
});

defineExpose({
  refreshGraphDisplay
});

watch(
  () => props.graph,
  async () => {
    if (pinnedNode.value) {
      const latest = (props.graph?.nodes || []).find((item) => item.id === pinnedNode.value.id);
      pinnedNode.value = latest || null;
      if (!latest) pinnedCardPoint.value = null;
    }
    await updateGraphData();
  },
  { deep: true }
);

watch(
  () => pinnedNodeDetail.value?.id,
  async (nodeId) => {
    if (!nodeId) return;
    await nextTick();
    const overlay = cardOverlayRef.value;
    if (!overlay) return;
    const width = Number(overlay.offsetWidth || 0);
    const height = Number(overlay.offsetHeight || 0);
    if (!width || !height) return;
    pinnedCardSize.value = { width, height };
  }
);

onMounted(async () => {
  await initGraph();
  setupResizeObserver();
});

onBeforeUnmount(() => {
  if (resizeRaf) {
    cancelAnimationFrame(resizeRaf);
    resizeRaf = 0;
  }
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  if (graphInstance) {
    unbindNodeClick();
    graphInstance.destroy();
    graphInstance = null;
  }
  pinnedNode.value = null;
  pinnedCardPoint.value = null;
});
</script>
