<template>
  <div ref="graphBodyRef" class="knowledge-graph-body knowledge-graph-body-full" :class="{ 'is-fullscreen': isFullscreen }">
    <div
      ref="graphContainerRef"
      class="knowledge-graph-canvas"
      :class="{ 'is-dragging': isGraphDragging }"
      role="img"
      :aria-label="graphAriaLabel"
      @pointerdown="startGraphDragCursor"
      @pointerup="endGraphDragCursor"
      @pointerleave="endGraphDragCursor"
      @pointercancel="endGraphDragCursor"
    ></div>

    <div v-if="showTools" class="knowledge-canvas-tools">
      <button class="btn graph-refresh-btn" type="button" aria-label="刷新图谱" title="刷新图谱" @click="refreshGraphDisplay">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M13.5 8a5.5 5.5 0 1 1-1.16-3.4" />
          <path d="M13.5 3.5v3.1h-3.1" />
        </svg>
      </button>
      <button
        class="btn graph-fullscreen-btn"
        type="button"
        :aria-label="fullscreenButtonLabel"
        :title="fullscreenButtonLabel"
        @click="toggleFullscreen"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path v-if="!isFullscreen" d="M6 2.5H2.5V6" />
          <path v-if="!isFullscreen" d="M10 2.5h3.5V6" />
          <path v-if="!isFullscreen" d="M2.5 10V13.5H6" />
          <path v-if="!isFullscreen" d="M10 13.5h3.5V10" />
          <path v-if="isFullscreen" d="M2.5 6h3.5V2.5" />
          <path v-if="isFullscreen" d="M13.5 6H10V2.5" />
          <path v-if="isFullscreen" d="M2.5 10h3.5v3.5" />
          <path v-if="isFullscreen" d="M13.5 10H10v3.5" />
        </svg>
      </button>
      <slot name="tools-extra"></slot>
    </div>

    <div v-if="directionLegendRows.length" class="knowledge-legend-overlay">
      <div
        v-for="(row, rowIndex) in directionLegendRows"
        :key="`legend-row-${rowIndex}`"
        class="legend-grid-row"
        :class="`is-cols-${row.length}`"
      >
        <button
          v-for="item in row"
          :key="item.id"
          class="legend-direction-item"
          :class="{
            'is-active': isDirectionHighlighted(item.id),
            'is-list': isDirectionListMode(item.id)
          }"
          type="button"
          :title="item.name"
          @click="toggleDirectionFocus(item.id)"
        >
          <span class="legend-dot legend-dot-direction" :style="item.dotStyle"></span>
          <span class="legend-direction-name">{{ item.name }}</span>
        </button>
      </div>
    </div>

    <aside v-if="directionPaperListItems.length" class="direction-paper-list-overlay">
      <header class="direction-paper-list-head">
        <div class="direction-paper-list-head-main">
          <p class="direction-paper-list-title">{{ selectedDirectionName }}</p>
          <span class="direction-paper-list-count mono">{{ directionPaperListItems.length }} 篇</span>
        </div>
        <button
          class="direction-paper-list-close"
          type="button"
          aria-label="关闭论文列表"
          title="关闭"
          @click="closeDirectionPaperList"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </header>

      <ul class="direction-paper-list">
        <li v-for="paper in directionPaperListItems" :key="paper.id">
          <button
            class="direction-paper-list-item"
            type="button"
            :title="paper.name"
            @click="focusPaperFromList(paper.id)"
          >
            <div class="direction-paper-list-item-top">
              <p class="direction-paper-list-item-title">{{ paper.name }}</p>
              <span class="direction-paper-list-item-relevance mono">{{ paper.relevancePercentText }}</span>
            </div>

            <p class="direction-paper-list-item-meta mono">
              {{ paper.publishedAtText }} · {{ paper.impactFactorText }} · {{ paper.citationCountText }} 引
            </p>

            <div class="direction-paper-list-item-tags">
              <span
                v-for="keyword in paper.keywords"
                :key="`${paper.id}-${keyword}`"
                class="direction-paper-list-item-tag"
              >
                {{ keyword }}
              </span>
            </div>

            <p class="direction-paper-list-item-abstract">{{ paper.abstractSnippet }}</p>
          </button>
        </li>
      </ul>
    </aside>

    <article
      v-if="pinnedNodeDetail"
      ref="cardOverlayRef"
      class="knowledge-node-card-overlay"
      :style="pinnedCardStyle"
    >
      <header class="paper-node-card-top">
        <div class="paper-node-title-wrap">
          <div class="paper-node-title-line">
            <a
              v-if="pinnedNodeDetail.isPaper && pinnedNodeDetail.url"
              class="paper-node-title paper-node-title-link"
              :href="pinnedNodeDetail.url"
              target="_blank"
              rel="noreferrer noopener"
            >
              {{ pinnedNodeDetail.name }}
            </a>
            <p v-else class="paper-node-title">{{ pinnedNodeDetail.name }}</p>
          </div>
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
        <div v-if="pinnedNodeDetail.keywords.length" class="paper-node-keywords">
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
            <p class="paper-node-metric-label">状态</p>
          </div>
          <p class="paper-node-metric-value">{{ pinnedNodeDetail.domainStatusText }}</p>
        </article>

        <article class="paper-node-metric">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">近2年占比</p>
          </div>
          <p class="paper-node-metric-value">{{ pinnedNodeDetail.domainRecentRatioText }}</p>
        </article>

        <article class="paper-node-metric">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">均引用</p>
          </div>
          <p class="paper-node-metric-value">{{ pinnedNodeDetail.domainAvgCitationsText }}</p>
        </article>

        <article class="paper-node-metric">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">论文数</p>
          </div>
          <p class="paper-node-metric-value">{{ pinnedNodeDetail.domainPaperCountText }}</p>
        </article>

        <article class="paper-node-metric paper-node-metric-wide">
          <div class="paper-node-metric-head">
            <p class="paper-node-metric-label">数据来源</p>
          </div>
          <p class="paper-node-metric-value">{{ pinnedNodeDetail.domainProviderText }}</p>
        </article>
      </section>

      <section v-if="pinnedNodeDetail.isDomain" class="paper-node-domain-block">
        <div class="paper-node-domain-section">
          <p class="paper-node-domain-title">核心论文</p>
          <div v-if="pinnedNodeDetail.domainCorePapers.length" class="paper-node-domain-list">
            <article
              v-for="paper in pinnedNodeDetail.domainCorePapers"
              :key="`${paper.title}-${paper.year}`"
              class="paper-node-domain-row"
            >
              <span class="paper-node-domain-year mono">{{ paper.year || '--' }}</span>
              <p class="paper-node-domain-name">{{ paper.title }}</p>
              <span class="paper-node-domain-cite mono">{{ paper.citationCount }} 引</span>
            </article>
          </div>
          <p v-else class="paper-node-domain-empty muted">暂无核心论文数据</p>
        </div>

        <div class="paper-node-domain-section">
          <p class="paper-node-domain-title">代表方法</p>
          <div v-if="pinnedNodeDetail.domainMethods.length" class="paper-node-domain-tags">
            <span v-for="method in pinnedNodeDetail.domainMethods" :key="method" class="paper-node-domain-tag mono">
              {{ method }}
            </span>
          </div>
          <p v-else class="paper-node-domain-empty muted">暂无方法标签</p>
        </div>
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
        <button
          class="paper-node-action-btn paper-node-star-btn"
          :class="{ 'is-active': pinnedNodeDetail.isBookmarked }"
          type="button"
          :disabled="bookmarkActionLoading || pinnedNodeDetail.isBookmarkSyncing"
          :aria-label="pinnedNodeDetail.isBookmarked ? '取消收藏' : '收藏论文'"
          :title="pinnedNodeDetail.isBookmarked ? '取消收藏' : '收藏论文'"
          @click="toggleBookmark"
        >
          <svg class="paper-node-star-icon" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M8 1.3l1.96 3.97 4.38.64-3.17 3.09.75 4.36L8 11.28l-3.92 2.08.75-4.36L1.66 5.91l4.38-.64L8 1.3z" />
          </svg>
        </button>
        <p v-if="bookmarkErrorMessage" class="paper-node-action-error mono">{{ bookmarkErrorMessage }}</p>
      </footer>
    </article>
  </div>
</template>

<script setup>
import { Graph } from '@antv/g6';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { buildKnowledgeNodeDetail } from './knowledgeNodeDetail';
import { clamp, normalizeRate, shortLabel } from './knowledgeGraphModel';
import { useAuthStore } from '../../stores/authStore';
import { useCollectionStore } from '../../stores/collectionStore';

const props = defineProps({
  graph: {
    type: Object,
    required: true
  },
  showTools: {
    type: Boolean,
    default: true
  }
});

const graphBodyRef = ref(null);
const graphContainerRef = ref(null);
const pinnedNode = ref(null);
const pinnedCardPoint = ref(null);
const cardOverlayRef = ref(null);
const pinnedCardSize = ref({ width: 460, height: 300 });
const selectedDirectionId = ref('');
const selectedDirectionMode = ref('none');
const isGraphDragging = ref(false);
const isFullscreen = ref(false);
const { accessToken, isAuthenticated, loadSession } = useAuthStore();
const { ensureBookmarkIndexLoaded, isPaperSaved, isPaperSyncing, togglePaperSaved } = useCollectionStore();
let graphInstance = null;
let resizeObserver = null;
let resizeRaf = 0;
let nodeClickHandler = null;
let lastGraphSignature = '';
const bookmarkActionLoading = ref(false);
const bookmarkErrorMessage = ref('');

const DIRECTION_MODE = Object.freeze({
  NONE: 'none',
  HIGHLIGHT: 'highlight',
  LIST: 'list'
});

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

const DIRECTION_BASE_COLORS = [
  '#2f80ed',
  '#ff9f1c',
  '#2ec27e',
  '#ff5d73',
  '#00b8d9',
  '#8e7dff',
  '#f6c945',
  '#43aa8b',
  '#f28482',
  '#7bd389'
];

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
const GRAPH_ZOOM_RANGE = [0.35, 2.2];

function hashText(value) {
  const input = String(value || '');
  let hash = 0;
  for (let index = 0; index < input.length; index += 1) {
    hash = (hash << 5) - hash + input.charCodeAt(index);
    hash |= 0;
  }
  return Math.abs(hash);
}

function parseHexColor(hex) {
  const value = String(hex || '').trim().replace('#', '');
  if (!/^[0-9a-fA-F]{6}$/.test(value)) {
    return null;
  }
  return {
    r: Number.parseInt(value.slice(0, 2), 16),
    g: Number.parseInt(value.slice(2, 4), 16),
    b: Number.parseInt(value.slice(4, 6), 16)
  };
}

function rgbToHex({ r, g, b }) {
  const toHex = (value) => clamp(Math.round(value), 0, 255).toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

function mixColor(fromColor, toColor, ratio) {
  const from = parseHexColor(fromColor);
  const to = parseHexColor(toColor);
  if (!from || !to) return fromColor;
  const safeRatio = clamp(Number(ratio) || 0, 0, 1);
  return rgbToHex({
    r: from.r * (1 - safeRatio) + to.r * safeRatio,
    g: from.g * (1 - safeRatio) + to.g * safeRatio,
    b: from.b * (1 - safeRatio) + to.b * safeRatio
  });
}

function parseDomainOrder(nodeId) {
  const matched = String(nodeId || '').match(/^domain:(\d+):/);
  if (!matched) return null;
  const parsed = Number.parseInt(matched[1], 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function directionPalette(baseColor, heat) {
  const normalizedHeat = normalizeRate(heat);
  const fill = mixColor(baseColor, '#ffffff', 0.54 - normalizedHeat * 0.18);
  const stroke = mixColor(baseColor, '#1f2937', 0.08 + normalizedHeat * 0.1);
  return { fill, stroke };
}

function buildColorContext(nodesRaw, edgesRaw) {
  const nodeKindById = new Map();
  const domainNodes = [];

  nodesRaw.forEach((node) => {
    const kind = node?.kind || node?.type || '';
    const id = String(node?.id || '');
    if (!id) return;
    nodeKindById.set(id, kind);
    if (kind === 'domain') domainNodes.push(node);
  });

  const domainPaletteById = new Map();
  domainNodes.forEach((node, index) => {
    const order = parseDomainOrder(node?.id);
    const paletteIndex = (Number.isFinite(order) ? order : index) % DIRECTION_BASE_COLORS.length;
    const baseColor = DIRECTION_BASE_COLORS[paletteIndex];
    const heat = normalizeRate(node?.relevance ?? node?.score);
    domainPaletteById.set(String(node.id), directionPalette(baseColor, heat));
  });

  const paperDomainById = new Map();
  edgesRaw.forEach((edge) => {
    const source = String(edge?.source || '');
    const target = String(edge?.target || '');
    if (!source || !target) return;
    if (nodeKindById.get(source) !== 'domain' || nodeKindById.get(target) !== 'paper') return;
    paperDomainById.set(target, source);
  });

  return { domainPaletteById, paperDomainById };
}

function selectedPaperNodeIdsByDirection(colorContext, directionId) {
  const targetDirectionId = String(directionId || '').trim();
  if (!targetDirectionId) return new Set();
  return new Set(
    [...colorContext.paperDomainById.entries()]
      .filter(([, domainId]) => domainId === targetDirectionId)
      .map(([paperId]) => paperId)
  );
}

function resolveNodePalette(node, colorContext) {
  const kind = node?.kind || node?.type || 'paper';
  if (kind === 'domain') {
    return colorContext.domainPaletteById.get(String(node?.id || '')) || NODE_STYLE.domain;
  }
  if (kind === 'paper') {
    const domainId = colorContext.paperDomainById.get(String(node?.id || ''));
    if (domainId) {
      const palette = colorContext.domainPaletteById.get(domainId);
      if (palette) return palette;
    }
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
    return clamp(360 - normalized * 210, 135, 360);
  }
  return clamp(430 - normalized * 150, 250, 430);
}

function graphPayloadSignature(graphPayload) {
  const nodes = Array.isArray(graphPayload?.nodes) ? graphPayload.nodes : [];
  const edges = Array.isArray(graphPayload?.edges) ? graphPayload.edges : [];
  const headNode = nodes[0] || {};
  const tailNode = nodes.at(-1) || {};
  const tailEdge = edges.at(-1) || {};
  return [
    nodes.length,
    edges.length,
    String(headNode.id || ''),
    String(tailNode.id || ''),
    String(headNode.name || headNode.label || ''),
    String(tailNode.name || tailNode.label || ''),
    String(tailEdge.id || ''),
    String(tailEdge.source || ''),
    String(tailEdge.target || '')
  ].join(':');
}

function isSingleSeedGraph(graphPayload) {
  const nodes = Array.isArray(graphPayload?.nodes) ? graphPayload.nodes : [];
  if (nodes.length !== 1) return false;
  const only = nodes[0] || {};
  return String(only.kind || only.type || '').toLowerCase() === 'seed';
}

function nodeSize(node, totalNodes) {
  const normalized = normalizeRate(node?.relevance ?? node?.score);
  if (node?.kind === 'seed') {
    return clamp(46 + totalNodes * 0.015, 46, 54);
  }
  if (node?.kind === 'domain') {
    return clamp(15 + normalized * 8.2, 15, 23);
  }
  return clamp(13 + normalized * 8.2, 13, 21.5);
}

function shouldRenderNodeLabel(nodeKind, totalNodes, isSelectedNode) {
  if (nodeKind === 'seed' || nodeKind === 'domain') return true;
  if (nodeKind !== 'paper') return false;
  return true;
}

function nodeLabelLimit(nodeKind, totalNodes) {
  if (nodeKind === 'seed') return 26;
  if (nodeKind === 'domain') return 18;
  if (nodeKind === 'paper') {
    if (totalNodes > 170) return 24;
    if (totalNodes > 120) return 28;
    return 34;
  }
  return 0;
}

function sortedDomainNodes(nodesRaw) {
  const domainNodes = nodesRaw.filter((node) => (node?.kind || node?.type) === 'domain');
  return domainNodes.sort((left, right) => {
    const a = parseDomainOrder(left?.id);
    const b = parseDomainOrder(right?.id);
    if (Number.isFinite(a) && Number.isFinite(b)) return a - b;
    if (Number.isFinite(a)) return -1;
    if (Number.isFinite(b)) return 1;
    return String(left?.name || left?.label || '').localeCompare(String(right?.name || right?.label || ''));
  });
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
  const edgeLabelEnabled = false;
  const colorContext = buildColorContext(nodesRaw, edgesRaw);
  const selectedDomainId = String(selectedDirectionId.value || '').trim();
  const hasSelection = Boolean(selectedDomainId) && selectedDirectionMode.value !== DIRECTION_MODE.NONE;
  const selectedPaperNodeIds = hasSelection
    ? selectedPaperNodeIdsByDirection(colorContext, selectedDomainId)
    : new Set();

  const nodes = nodesRaw.map((node) => {
    const kind = node.kind || node.type || 'paper';
    const palette = resolveNodePalette(node, colorContext);
    const size = nodeSize(node, totalNodes);
    const nodeId = String(node.id || '');
    const isSelectedNode = (
      (kind === 'domain' && nodeId === selectedDomainId)
      || (kind === 'paper' && selectedPaperNodeIds.has(nodeId))
    );
    const isDimmedNode = hasSelection && kind !== 'seed' && !isSelectedNode;
    const nodeOpacity = kind === 'seed' ? (hasSelection ? 0.6 : 1) : (isDimmedNode ? 0.16 : 1);
    const showLabel = shouldRenderNodeLabel(kind, totalNodes, isSelectedNode);
    const labelText = showLabel
      ? shortLabel(node.name || node.label, nodeLabelLimit(kind, totalNodes))
      : '';
    return {
      id: node.id,
      data: {
        ...node,
        nodeKind: kind,
        resolvedSize: size,
        isSelectedNode
      },
      style: {
        size,
        fill: palette.fill,
        stroke: palette.stroke,
        lineWidth: isSelectedNode
          ? (kind === 'domain' ? 2.6 : 2.1)
          : (kind === 'seed' ? 3.1 : (kind === 'domain' ? 1.45 : 1.2)),
        shadowBlur: isSelectedNode ? 9 : (kind === 'seed' ? 10 : 4),
        shadowColor: kind === 'seed' ? 'rgba(31, 119, 180, 0.36)' : 'rgba(0, 0, 0, 0.04)',
        label: showLabel,
        labelText,
        labelPlacement: 'bottom',
        labelOffsetY: kind === 'paper' ? 4 : 6,
        labelFontSize: kind === 'seed' ? 12 : (kind === 'domain' ? 10 : 9),
        labelFontWeight: kind === 'seed' ? 700 : 500,
        labelFill: '#2f2f2f',
        labelBackground: false,
        cursor: 'pointer',
        opacity: nodeOpacity
      }
    };
  });

  const edges = edgesRaw.map((edge, index) => {
    const kind = edge?.kind || 'center';
    const relevance = normalizeRate(edge?.relevance ?? edge?.weight);
    const sourceId = String(edge?.source || '');
    const targetId = String(edge?.target || '');
    const isSelectedEdge = hasSelection && (
      sourceId === selectedDomainId
      || targetId === selectedDomainId
      || (sourceId === selectedDomainId && selectedPaperNodeIds.has(targetId))
    );
    const isDimmedEdge = hasSelection && !isSelectedEdge;
    return {
      id: edge.id || `edge-${index}`,
      source: sourceId,
      target: targetId,
      data: {
        ...edge,
        kind,
        relevance,
        isSelectedEdge
      },
      style: {
        stroke: edgeStroke(relevance, kind),
        lineWidth: isSelectedEdge
          ? edgeWidth(relevance, kind) * 1.35
          : edgeWidth(relevance, kind),
        strokeOpacity: isDimmedEdge ? 0.12 : 1,
        endArrow: false,
        lineDash: relevance < 0.35 ? [5, 4] : undefined,
        label: !isDimmedEdge && edgeLabelEnabled && kind === 'center'
      }
    };
  });

  return { nodes, edges };
}

function buildLayout(width, height, totalNodes, edgeCount) {
  if (totalNodes <= 1) {
    return {
      type: 'd3-force',
      animation: false,
      preventOverlap: false,
      center: [width / 2, height / 2],
      alphaDecay: 1,
      velocityDecay: 1,
      iterations: 1,
      manyBody: {
        strength: 0,
        distanceMax: 1
      },
      link: {
        distance: 160,
        strength: 0
      },
      collide: {
        strength: 0,
        iterations: 1,
        radius: () => 0
      }
    };
  }
  const crowdFactor = clamp(edgeCount / Math.max(1, totalNodes), 1.2, 6.2);
  return {
    type: 'd3-force',
    animation: true,
    preventOverlap: true,
    center: [width / 2, height / 2],
    alphaDecay: 0.07,
    velocityDecay: 0.44,
    iterations: 280,
    manyBody: {
      strength: -700 - crowdFactor * 65,
      distanceMax: 1300
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
      strength: 0.92,
      iterations: 6,
      radius: (node) => Number(node?.data?.resolvedSize || 11) / 2 + 22
    }
  };
}

function graphOptions(width, height) {
  const data = toG6Data(props.graph);
  return {
    width,
    height,
    zoomRange: GRAPH_ZOOM_RANGE,
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

function getViewportSnapshot() {
  if (!graphInstance) return null;
  try {
    const zoom = Number(graphInstance.getZoom?.());
    const position = normalizePoint(graphInstance.getPosition?.());
    if (!Number.isFinite(zoom) || !position) return null;
    return { zoom, position };
  } catch {
    return null;
  }
}

async function restoreViewport(snapshot) {
  if (!graphInstance || !snapshot) return;
  try {
    if (graphInstance.zoomTo) {
      await graphInstance.zoomTo(snapshot.zoom, { duration: 0 });
    }
    if (graphInstance.translateTo) {
      await graphInstance.translateTo(snapshot.position, { duration: 0 });
    }
  } catch {
    // no-op
  }
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
    if ((node?.kind || node?.type) === 'seed') {
      closePinnedCard();
      return;
    }

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
  if (isSingleSeedGraph(props.graph) && graphInstance?.zoomTo) {
    await graphInstance.zoomTo(1, { duration: 0 });
  }
  lastGraphSignature = graphPayloadSignature(props.graph);
  bindNodeClick();
}

async function updateGraphData() {
  if (!graphInstance) {
    await initGraph();
    return;
  }
  const { width, height } = getContainerSize();
  const singleSeed = isSingleSeedGraph(props.graph);
  const viewport = singleSeed ? null : getViewportSnapshot();
  graphInstance.setOptions(graphOptions(width, height));
  await graphInstance.render();
  if (singleSeed && graphInstance?.zoomTo) {
    await graphInstance.zoomTo(1, { duration: 0 });
  } else {
    await restoreViewport(viewport);
  }
  lastGraphSignature = graphPayloadSignature(props.graph);
}

async function recreateGraph({ fitView = false } = {}) {
  if (graphInstance) {
    unbindNodeClick();
    graphInstance.destroy();
    graphInstance = null;
  }
  await initGraph();
  if (fitView && graphInstance?.fitView) {
    try {
      await graphInstance.fitView();
    } catch {
      // no-op
    }
  }
  if (isSingleSeedGraph(props.graph) && graphInstance?.zoomTo) {
    try {
      await graphInstance.zoomTo(1, { duration: 0 });
    } catch {
      // no-op
    }
  }
  lastGraphSignature = graphPayloadSignature(props.graph);
}

async function refreshGraphDisplay() {
  closePinnedCard();
  if (selectedDirectionId.value || selectedDirectionMode.value !== DIRECTION_MODE.NONE) {
    resetDirectionSelection();
    await nextTick();
  }
  await recreateGraph({ fitView: true });
}

async function zoomToMinOverview() {
  if (!graphInstance) return;
  const minZoom = Number(GRAPH_ZOOM_RANGE?.[0]);
  if (!Number.isFinite(minZoom)) return;
  try {
    if (graphInstance.fitView) {
      await graphInstance.fitView();
    }
    if (graphInstance.zoomTo) {
      await graphInstance.zoomTo(minZoom, { duration: 240 });
    }
  } catch {
    // no-op
  }
}

async function refreshGraphToMinOverview() {
  await refreshGraphDisplay();
  await zoomToMinOverview();
}

function updateFullscreenState() {
  const layout = graphBodyRef.value?.closest?.('.workflow-layout');
  if (!layout) {
    isFullscreen.value = false;
    return;
  }
  isFullscreen.value = layout.classList.contains('is-graph-fullscreen');
}

async function toggleFullscreen() {
  const layout = graphBodyRef.value?.closest?.('.workflow-layout');
  if (!layout) return;
  const nextState = !layout.classList.contains('is-graph-fullscreen');
  layout.classList.toggle('is-graph-fullscreen', nextState);
  isFullscreen.value = nextState;
  await nextTick();
  await updateGraphData();
}

function setupResizeObserver() {
  if (!graphContainerRef.value) return;
  resizeObserver = new ResizeObserver(() => {
    if (resizeRaf) cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(async () => {
      resizeRaf = 0;
      if (!graphInstance) return;
      const { width, height } = getContainerSize();
      const viewport = getViewportSnapshot();
      graphInstance.resize(width, height);
      graphInstance.setOptions(graphOptions(width, height));
      await graphInstance.render();
      await restoreViewport(viewport);
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

function splitAuthorsToList(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).filter(Boolean);
  }
  return String(value || '')
    .split(/[;,，]/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildPaperMetadataFromGraphNode(node, detail) {
  const meta = node?.meta && typeof node.meta === 'object' ? node.meta : {};
  const yearRaw = Number(meta?.year);
  const year = Number.isFinite(yearRaw) ? Math.round(yearRaw) : null;
  const citationRaw = Number(meta?.citation_count);
  const citationCount = Number.isFinite(citationRaw) ? Math.max(0, Math.round(citationRaw)) : 0;
  const impactRaw = Number(meta?.impact_factor);
  const impactFactor = Number.isFinite(impactRaw) ? Math.max(0, impactRaw) : null;
  const publicationDate = String(meta?.publication_date || '').trim();
  const fieldsOfStudy = Array.isArray(meta?.fields_of_study)
    ? meta.fields_of_study.map((item) => String(item || '').trim()).filter(Boolean)
    : String(meta?.fields_of_study || '')
      .split(/[;,，]/g)
      .map((item) => item.trim())
      .filter(Boolean);
  return {
    title: String(detail?.name || node?.label || '').trim(),
    abstract: String(meta?.abstract || '').trim(),
    authors: splitAuthorsToList(meta?.authors),
    year,
    publication_date: publicationDate,
    citation_count: citationCount,
    impact_factor: impactFactor,
    fields_of_study: fieldsOfStudy,
    venue: String(meta?.venue || '').trim(),
    url: String(meta?.url || '').trim()
  };
}

function resolvePaperIdForNode(node) {
  const direct = String(node?.paper_id || '').trim();
  if (direct) return direct;
  const metaId = String(node?.meta?.paper_id || '').trim();
  if (metaId) return metaId;
  const nodeId = String(node?.id || '').trim();
  if (nodeId.startsWith('paper:')) return nodeId.slice('paper:'.length).trim() || nodeId;
  return nodeId;
}

async function toggleBookmark() {
  const detail = pinnedNodeDetail.value;
  if (!detail || !detail.isPaper) return;
  if (detail.isBookmarkSyncing) return;
  if (bookmarkActionLoading.value) return;

  const node = pinnedNode.value;
  const paperId = String(detail.paperId || resolvePaperIdForNode(node)).trim();
  if (!paperId) return;
  bookmarkErrorMessage.value = '';
  bookmarkActionLoading.value = true;
  try {
    if (!isAuthenticated.value || !String(accessToken.value || '').trim()) {
      await loadSession();
    }
    const token = String(accessToken.value || '').trim();
    if (!token) {
      bookmarkErrorMessage.value = '请先登录后再收藏。';
      return;
    }
    await togglePaperSaved({
      accessToken: token,
      paperId,
      metadata: buildPaperMetadataFromGraphNode(node, detail)
    });
  } catch (error) {
    bookmarkErrorMessage.value = error?.message || '收藏失败，请稍后重试。';
  } finally {
    bookmarkActionLoading.value = false;
  }
}

function startGraphDragCursor() {
  isGraphDragging.value = true;
}

function endGraphDragCursor() {
  isGraphDragging.value = false;
}

function isDirectionHighlighted(directionId) {
  const target = String(directionId || '').trim();
  return (
    target
    && selectedDirectionMode.value !== DIRECTION_MODE.NONE
    && selectedDirectionId.value === target
  );
}

function isDirectionListMode(directionId) {
  const target = String(directionId || '').trim();
  return (
    target
    && selectedDirectionMode.value === DIRECTION_MODE.LIST
    && selectedDirectionId.value === target
  );
}

function resetDirectionSelection() {
  selectedDirectionId.value = '';
  selectedDirectionMode.value = DIRECTION_MODE.NONE;
}

function closeDirectionPaperList() {
  if (selectedDirectionMode.value !== DIRECTION_MODE.LIST) return;
  resetDirectionSelection();
}

function resolveDirectionFocusNodeIds(directionId) {
  const targetId = String(directionId || '').trim();
  if (!targetId) return [];

  const nodesRaw = Array.isArray(props.graph?.nodes) ? props.graph.nodes : [];
  const edgesRaw = Array.isArray(props.graph?.edges) ? props.graph.edges : [];
  const knownNodeIds = new Set(
    nodesRaw
      .map((node) => String(node?.id || '').trim())
      .filter(Boolean)
  );
  if (!knownNodeIds.has(targetId)) return [];

  const colorContext = buildColorContext(nodesRaw, edgesRaw);
  const relatedPaperIds = selectedPaperNodeIdsByDirection(colorContext, targetId);
  const focusIds = [targetId];
  for (const paperId of relatedPaperIds) {
    if (!knownNodeIds.has(paperId)) continue;
    focusIds.push(paperId);
  }
  return focusIds;
}

function computeFocusZoomTarget(nodeIds) {
  if (!graphInstance || !Array.isArray(nodeIds) || !nodeIds.length) return null;
  const points = nodeIds
    .map((nodeId) => normalizePoint(graphInstance.getElementPosition?.(nodeId)))
    .filter(Boolean);
  if (!points.length) return null;

  const currentZoomRaw = Number(graphInstance.getZoom?.());
  const currentZoom = Number.isFinite(currentZoomRaw) && currentZoomRaw > 0
    ? currentZoomRaw
    : 1;
  const preferredZoom = currentZoom * 0.86;

  if (points.length < 2) {
    return clamp(preferredZoom, GRAPH_ZOOM_RANGE[0], GRAPH_ZOOM_RANGE[1]);
  }

  const xValues = points.map((point) => point.x);
  const yValues = points.map((point) => point.y);
  const minX = Math.min(...xValues);
  const maxX = Math.max(...xValues);
  const minY = Math.min(...yValues);
  const maxY = Math.max(...yValues);
  const boxWidth = Math.max(1, maxX - minX);
  const boxHeight = Math.max(1, maxY - minY);

  const { width, height } = getContainerSize();
  const availableWidth = Math.max(80, width - 220);
  const availableHeight = Math.max(80, height - 160);
  const fitScale = Math.min(availableWidth / boxWidth, availableHeight / boxHeight);
  const fitZoom = currentZoom * fitScale * 0.92;
  const targetZoom = Math.min(preferredZoom, fitZoom);
  return clamp(targetZoom, GRAPH_ZOOM_RANGE[0], GRAPH_ZOOM_RANGE[1]);
}

async function focusDirectionNode(directionId) {
  if (!graphInstance) return;
  const targetId = String(directionId || '').trim();
  if (!targetId) return;
  const focusIds = resolveDirectionFocusNodeIds(targetId);
  const focusTarget = focusIds.length ? focusIds : [targetId];
  try {
    if (graphInstance.focusElement) {
      await graphInstance.focusElement(focusTarget, { duration: 260 });
    } else {
      const point = normalizePoint(graphInstance.getElementPosition?.(targetId));
      if (point && graphInstance.translateTo) {
        await graphInstance.translateTo(point, { duration: 260 });
      }
    }
  } catch {
    // fallback to translateTo if focusElement fails
    try {
      const point = normalizePoint(graphInstance.getElementPosition?.(targetId));
      if (point && graphInstance.translateTo) {
        await graphInstance.translateTo(point, { duration: 260 });
      }
    } catch {
      // no-op
    }
  }

  const targetZoom = computeFocusZoomTarget(focusTarget);
  if (targetZoom == null || !graphInstance.zoomTo) return;
  try {
    await graphInstance.zoomTo(targetZoom, { duration: 260 });
  } catch {
    // no-op
  }
}

async function toggleDirectionFocus(directionId) {
  const nextId = String(directionId || '').trim();
  if (!nextId) return;
  const isSameDirection = selectedDirectionId.value === nextId;

  if (!isSameDirection) {
    selectedDirectionId.value = nextId;
    selectedDirectionMode.value = DIRECTION_MODE.HIGHLIGHT;
    await nextTick();
    await focusDirectionNode(nextId);
    return;
  }

  if (selectedDirectionMode.value === DIRECTION_MODE.NONE) {
    selectedDirectionMode.value = DIRECTION_MODE.HIGHLIGHT;
    await nextTick();
    await focusDirectionNode(nextId);
    return;
  }
  if (selectedDirectionMode.value === DIRECTION_MODE.HIGHLIGHT) {
    selectedDirectionMode.value = DIRECTION_MODE.LIST;
    await nextTick();
    await focusDirectionNode(nextId);
    return;
  }

  resetDirectionSelection();
}

function focusPaperFromList(paperId) {
  const targetPaperId = String(paperId || '').trim();
  if (!targetPaperId) return;
  const targetNode = (props.graph?.nodes || []).find((node) => (
    String(node?.id || '') === targetPaperId && (node?.kind || node?.type) === 'paper'
  ));
  if (!targetNode) return;
  pinnedNode.value = targetNode;
  pinnedCardPoint.value = null;
}

const graphAriaLabel = computed(() => `${props.graph?.title || '知识图谱'}可视化`);
const fullscreenButtonLabel = computed(() => (isFullscreen.value ? '收回' : '全屏'));

const directionLegendItems = computed(() => {
  const sorted = sortedDomainNodes(props.graph?.nodes || []);

  return sorted.map((node, index) => {
    const order = parseDomainOrder(node?.id);
    const paletteIndex = (Number.isFinite(order) ? order : index) % DIRECTION_BASE_COLORS.length;
    const baseColor = DIRECTION_BASE_COLORS[paletteIndex];
    const heat = normalizeRate(node?.relevance ?? node?.score);
    const palette = directionPalette(baseColor, heat);
    const name = String(node?.name || node?.label || `子方向 ${index + 1}`).trim();
    return {
      id: String(node?.id || `legend-direction-${index}`),
      name,
      dotStyle: {
        background: palette.fill,
        borderColor: palette.stroke
      }
    };
  });
});

const directionLegendRows = computed(() => {
  const items = directionLegendItems.value;
  const rows = [
    items.slice(0, 3),
    items.slice(3, 6),
    items.slice(6, 10)
  ];
  return rows.filter((row) => row.length > 0);
});

const selectedDirectionName = computed(() => {
  const selectedId = String(selectedDirectionId.value || '').trim();
  if (!selectedId) return '子方向论文列表';
  const matched = directionLegendItems.value.find((item) => item.id === selectedId);
  return matched?.name || '子方向论文列表';
});

const directionPaperListItems = computed(() => {
  if (selectedDirectionMode.value !== DIRECTION_MODE.LIST) return [];
  const selectedId = String(selectedDirectionId.value || '').trim();
  if (!selectedId) return [];

  const nodesRaw = Array.isArray(props.graph?.nodes) ? props.graph.nodes : [];
  const edgesRaw = Array.isArray(props.graph?.edges) ? props.graph.edges : [];
  const colorContext = buildColorContext(nodesRaw, edgesRaw);
  const selectedPaperIds = selectedPaperNodeIdsByDirection(colorContext, selectedId);
  if (!selectedPaperIds.size) return [];

  const paperNodes = nodesRaw
    .filter((node) => selectedPaperIds.has(String(node?.id || '')))
    .filter((node) => (node?.kind || node?.type) === 'paper')
    .sort((left, right) => {
      const relevanceDiff = normalizeRate(right?.relevance ?? right?.score) - normalizeRate(left?.relevance ?? left?.score);
      if (Math.abs(relevanceDiff) > 1e-6) return relevanceDiff;
      const citationDiff = Number(right?.meta?.citation_count || 0) - Number(left?.meta?.citation_count || 0);
      if (citationDiff) return citationDiff;
      return String(left?.name || left?.label || '').localeCompare(String(right?.name || right?.label || ''));
    });

  return paperNodes
    .map((node) => buildKnowledgeNodeDetail(node))
    .filter(Boolean)
    .map((detail) => ({
      id: detail.id,
      name: detail.name,
      relevancePercentText: detail.relevancePercentText,
      publishedAtText: detail.publishedAtText,
      impactFactorText: detail.impactFactorText,
      citationCountText: detail.citationCountText,
      keywords: detail.keywords?.slice(0, 4) || [],
      abstractSnippet: detail.abstractSnippet
    }));
});

const pinnedNodeDetail = computed(() => {
  const detail = buildKnowledgeNodeDetail(pinnedNode.value);
  if (!detail) return null;
  const paperId = detail.isPaper ? resolvePaperIdForNode(pinnedNode.value) : '';
  return {
    ...detail,
    paperId,
    isBookmarked: paperId ? isPaperSaved(paperId) : false,
    isBookmarkSyncing: paperId ? isPaperSyncing(paperId) : false
  };
});

const pinnedCardStyle = computed(() => {
  const width = graphContainerRef.value?.clientWidth || 920;
  const height = graphContainerRef.value?.clientHeight || 560;
  const measuredWidth = Number(cardOverlayRef.value?.offsetWidth || pinnedCardSize.value.width || 0);
  const measuredHeight = Number(cardOverlayRef.value?.offsetHeight || pinnedCardSize.value.height || 0);
  const cardWidth = clamp(measuredWidth || 420, 320, Math.max(320, width - 24));
  const maxHeight = Math.max(220, height - 20);
  const cardHeight = clamp(measuredHeight || 320, 220, maxHeight);
  const topInset = 10;
  const leftInset = 12;
  const leftCandidate = (width - cardWidth) / 2;
  const topCandidate = (height - cardHeight) / 2;
  const safeLeft = clamp(leftCandidate, leftInset, Math.max(leftInset, width - cardWidth - leftInset));
  const safeTop = clamp(topCandidate, topInset, Math.max(topInset, height - cardHeight - topInset));

  return {
    left: `${safeLeft}px`,
    top: `${safeTop}px`,
    width: `${Math.round(cardWidth)}px`,
    maxHeight: `${Math.round(maxHeight)}px`
  };
});

defineExpose({
  refreshGraphDisplay,
  refreshGraphToMinOverview
});

watch(
  () => props.graph,
  async () => {
    const signature = graphPayloadSignature(props.graph);
    if (signature === lastGraphSignature) {
      return;
    }
    if (selectedDirectionId.value) {
      const hasSelectedDirection = (props.graph?.nodes || []).some((item) => (
        item?.kind === 'domain' && String(item.id || '') === selectedDirectionId.value
      ));
      if (!hasSelectedDirection) {
        selectedDirectionId.value = '';
        selectedDirectionMode.value = DIRECTION_MODE.NONE;
      }
    }
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
  [selectedDirectionId, selectedDirectionMode],
  async () => {
    await updateGraphData();
  }
);

watch(
  () => pinnedNodeDetail.value?.id,
  async (nodeId) => {
    bookmarkErrorMessage.value = '';
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
  window.addEventListener('pointerup', endGraphDragCursor);
  window.addEventListener('pointercancel', endGraphDragCursor);
  updateFullscreenState();
  if (isAuthenticated.value && String(accessToken.value || '').trim()) {
    void ensureBookmarkIndexLoaded({ accessToken: accessToken.value });
  }
});

watch(
  () => [isAuthenticated.value, String(accessToken.value || '').trim()],
  ([authenticated, token]) => {
    if (!authenticated || !token) return;
    void ensureBookmarkIndexLoaded({ accessToken: token });
  },
  { deep: true }
);

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
  window.removeEventListener('pointerup', endGraphDragCursor);
  window.removeEventListener('pointercancel', endGraphDragCursor);
  const layout = graphBodyRef.value?.closest?.('.workflow-layout');
  if (layout && layout.classList.contains('is-graph-fullscreen')) {
    layout.classList.remove('is-graph-fullscreen');
  }
  pinnedNode.value = null;
  pinnedCardPoint.value = null;
  isGraphDragging.value = false;
  isFullscreen.value = false;
});
</script>
