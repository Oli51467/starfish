<template>
  <section class="blood-lineage">
    <div class="blood-main">
      <div
        ref="canvasRef"
        class="blood-canvas-wrap"
        :class="{ 'is-dragging': isCanvasDragging, 'is-fullscreen': isFullscreen }"
        @wheel.prevent="handleCanvasWheel"
        @pointerdown="handleCanvasPointerDown"
        @pointermove="handleCanvasPointerMove"
        @pointerup="handleCanvasPointerUp"
        @pointercancel="handleCanvasPointerUp"
      >
        <div class="blood-canvas-head">
          <div class="blood-canvas-head-right">
            <button
              class="btn graph-refresh-btn blood-canvas-refresh"
              type="button"
              aria-label="刷新血缘树"
              title="刷新血缘树"
              @pointerdown.stop
              @pointermove.stop
              @pointerup.stop
              @click="refreshLineageDisplay"
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="M13.5 8a5.5 5.5 0 1 1-1.16-3.4" />
                <path d="M13.5 3.5v3.1h-3.1" />
              </svg>
            </button>
            <button
              class="btn graph-fullscreen-btn blood-canvas-fullscreen"
              type="button"
              :aria-label="fullscreenButtonLabel"
              :title="fullscreenButtonLabel"
              @pointerdown.stop
              @pointermove.stop
              @pointerup.stop
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
            <div
              v-if="$slots['tools-extra']"
              class="blood-tools-extra"
              @pointerdown.stop
              @pointermove.stop
              @pointerup.stop
            >
              <slot name="tools-extra"></slot>
            </div>
          </div>
        </div>

        <div class="blood-time-axis">
          <div class="blood-time-axis-track" :style="timelineViewportStyle">
            <div
              v-for="tick in yearTicks"
              :key="`tick-${tick.year}`"
              class="blood-year-line"
              :style="{ left: `${tick.x}px` }"
            >
              <span class="blood-year-label mono">{{ tick.year }}</span>
            </div>
          </div>
        </div>

        <svg :key="`lineage-svg-${renderNonce}`" class="blood-svg" :viewBox="`0 0 ${viewBox.width} ${viewBox.height}`">
          <defs>
            <marker
              v-for="marker in citationMarkers"
              :id="`lineage-arrow-${marker.key}`"
              :key="`arrow-${marker.key}`"
              viewBox="0 -4 8 8"
              refX="18"
              refY="0"
              markerWidth="5"
              markerHeight="5"
              orient="auto"
            >
              <path d="M0,-4L8,0L0,4" :fill="marker.color" />
            </marker>
          </defs>

          <g :transform="canvasViewportTransform">
            <g class="blood-edge-layer">
              <path
                v-for="edge in layoutEdges"
                :key="edge.id"
                :d="edge.path"
                fill="none"
                :stroke="edge.color"
                :stroke-width="edge.strokeWidth"
                :stroke-opacity="edge.opacity"
                :marker-end="`url(#lineage-arrow-${edge.citationType})`"
              />
            </g>

            <g class="blood-node-layer">
              <g
                v-for="node in layoutNodes"
                :key="node.id"
                class="blood-node-group"
                :class="{ 'is-dragging': draggingNodeId === node.id }"
                :transform="`translate(${node.x}, ${node.y})`"
                @mouseenter="showTooltip($event, node)"
                @mouseleave="hideTooltip"
                @click="openDetail(node)"
                @pointerdown.stop="startNodeDrag($event, node)"
              >
                <circle
                  v-if="node.nodeType === 'root'"
                  :r="node.radius + 8"
                  class="blood-root-ring"
                />
                <circle
                  :r="node.radius"
                  :fill="node.fill"
                  :stroke="node.stroke"
                  :stroke-width="node.strokeWidth"
                />
                <text class="blood-node-year mono" text-anchor="middle" dy="-3" :fill="node.yearFill">{{ node.yearText }}</text>
                <text class="blood-node-cite mono" text-anchor="middle" dy="8" :fill="node.citationFill">{{ node.citationText }}</text>
                <text
                  class="blood-node-label"
                  text-anchor="middle"
                  :dy="node.labelDy"
                >
                  {{ node.shortTitle }}
                </text>
              </g>
            </g>
          </g>
        </svg>

        <div class="blood-legend">
          <p class="blood-legend-title mono">Citation type</p>
          <div v-for="marker in citationMarkers" :key="`legend-${marker.key}`" class="blood-legend-row">
            <span class="blood-legend-line" :style="{ background: marker.color }"></span>
            <span>{{ marker.label }}</span>
          </div>
        </div>

        <div v-if="tooltip.visible" class="blood-tooltip" :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }">
          <p class="blood-tooltip-title">{{ tooltip.title }}</p>
          <p class="blood-tooltip-meta mono">{{ tooltip.meta }}</p>
        </div>
      </div>

      <aside class="blood-detail-panel" :class="{ 'is-open': Boolean(selectedNode) }">
        <header class="blood-detail-head">
          <p class="blood-detail-title">{{ selectedNode?.title || '选择节点查看详情' }}</p>
          <button class="blood-detail-close" type="button" @click="selectedNode = null">✕</button>
        </header>
        <div v-if="selectedNode" class="blood-detail-body">
          <p class="blood-detail-meta mono">{{ detailMeta }}</p>
          <div class="blood-detail-tags">
            <span class="blood-detail-tag">{{ selectedNodeInfo.nodeRoleLabel }}</span>
            <span v-if="selectedNodeInfo.relationLabel" class="blood-detail-tag">{{ selectedNodeInfo.relationLabel }}</span>
          </div>

          <div class="blood-detail-grid">
            <article
              v-for="item in selectedNodeInfo.metaItems"
              :key="item.label"
              class="blood-detail-grid-item"
            >
              <p class="blood-detail-grid-label mono">{{ item.label }}</p>
              <p class="blood-detail-grid-value">{{ item.value }}</p>
            </article>
          </div>

          <section v-if="selectedNodeInfo.relationDescription" class="blood-detail-section">
            <p class="blood-detail-section-title mono">关系说明</p>
            <p class="blood-detail-text">{{ selectedNodeInfo.relationDescription }}</p>
          </section>

          <section class="blood-detail-section">
            <p class="blood-detail-section-title mono">摘要</p>
            <p class="blood-detail-text">{{ selectedNodeInfo.abstractText }}</p>
          </section>

          <a
            v-if="selectedNodeInfo.url"
            class="blood-detail-link mono"
            :href="selectedNodeInfo.url"
            target="_blank"
            rel="noopener noreferrer"
          >
            查看原文
          </a>
          <p class="blood-detail-id mono">{{ selectedNodeInfo.paperId }}</p>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = defineProps({
  lineage: {
    type: Object,
    required: true
  },
  stretchTimeline: {
    type: Boolean,
    default: false
  }
});

const canvasRef = ref(null);
const isFullscreen = ref(false);
const selectedNode = ref(null);
const renderNonce = ref(0);
const viewBox = ref({
  width: 920,
  height: 560
});
const tooltip = ref({
  visible: false,
  x: 0,
  y: 0,
  title: '',
  meta: ''
});
const viewport = ref({
  x: 0,
  y: 0,
  scale: 1
});
const panState = ref({
  active: false,
  pointerId: null,
  startX: 0,
  startY: 0,
  originX: 0,
  originY: 0,
  metrics: null
});
const nodeDragState = ref({
  active: false,
  pointerId: null,
  nodeId: '',
  node: null,
  startX: 0,
  startY: 0,
  originOffsetX: 0,
  originOffsetY: 0,
  moved: false,
  metrics: null
});
const nodeOffsetMap = ref({});
const suppressNodeClick = ref({
  nodeId: '',
  expiresAt: 0
});
let resizeObserver = null;

const VIEWPORT_DEFAULT_MIN_SCALE = 0.56;
const VIEWPORT_ABSOLUTE_MIN_SCALE = 0.06;
const VIEWPORT_MAX_SCALE = 2.6;
const FULLSCREEN_HOST_SELECTOR = '.workflow-layout, .history-layout';
const NODE_DRAG_THRESHOLD = 3;
const WHEEL_ZOOM_SENSITIVITY = Object.freeze({
  tiny: 0.004,
  small: 0.0026,
  medium: 0.0018,
  large: 0.001,
  huge: 0.00055,
  extreme: 0.0003
});
const WHEEL_DELTA_LIMIT = 640;
const WHEEL_MIN_EFFECT_DELTA = 0.05;
const VIEWPORT_FIT_PADDING = 96;
const STRETCHED_TIMELINE_SIDE_RATIO = 0.08;
const STRETCHED_TIMELINE_SIDE_MIN = 52;
const STRETCHED_TIMELINE_SIDE_MAX = 128;
const YEAR_MIN_BOUND = 1950;
const YEAR_MAX_FUTURE_OFFSET = 2;
const SPARSE_TIMELINE_DENSITY_THRESHOLD = 0.6;
const SPARSE_TIMELINE_MIN_SPAN = 6;
const DESCENDANT_LABEL_GAP_BOOST = 1.36;
const DESCENDANT_LABEL_BOTTOM_EXTRA = 52;
const TIMELINE_LEFT_RATIO = 0.12;
const TIMELINE_RIGHT_RATIO = 0.12;
const LAYOUT_SPACING = {
  compact: {
    centerBandGap: 5,
    yearRowGap: 74,
    generationGap: 176,
    relevanceShift: 50,
    yearLaneGap: 59,
    nodeMinGap: 138,
    labelMinGap: 104,
    nodeCollisionPadding: 16,
    maxColumnsPerYear: 1
  },
  regular: {
    centerBandGap: 6,
    yearRowGap: 110,
    generationGap: 256,
    relevanceShift: 74,
    yearLaneGap: 90,
    nodeMinGap: 190,
    labelMinGap: 149,
    nodeCollisionPadding: 22,
    maxColumnsPerYear: 1
  }
};

const citationConfig = {
  extending: { label: 'Extending', color: 'var(--info)' },
  supporting: { label: 'Supporting', color: 'var(--success)' },
  contradicting: { label: 'Contradicting', color: 'var(--accent)' },
  migrating: { label: 'Migrating', color: 'var(--violet)' },
  mentioning: { label: 'Mentioning', color: 'var(--muted)' }
};

const citationMarkers = Object.entries(citationConfig).map(([key, value]) => ({
  key,
  label: value.label,
  color: value.color
}));
const citationTypeLabelZh = Object.freeze({
  extending: '扩展',
  supporting: '支持',
  contradicting: '反驳',
  migrating: '迁移',
  mentioning: '提及'
});
const nodeRoleLabelZh = Object.freeze({
  root: '核心论文',
  ancestor: '祖先论文',
  descendant: '后代论文'
});

function resolvePaperId(node) {
  return String(node?.paper_id || node?.paperId || node?.id || '').trim();
}

function textOrFallback(value, fallback = '-') {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function normalizeCitationType(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(citationConfig, normalized)) {
    return normalized;
  }
  return 'mentioning';
}

function normalizeGeneration(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return 1;
  return Math.max(0, Math.round(parsed));
}

function normalizeCitationCount(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return Math.round(parsed);
}

function resolveCitationTypeLabel(type) {
  const normalized = normalizeCitationType(type);
  return citationTypeLabelZh[normalized] || citationConfig[normalized]?.label || citationTypeLabelZh.mentioning;
}

function resolveNodeRoleLabel(node) {
  const key = String(node?.nodeType || '').trim().toLowerCase();
  return nodeRoleLabelZh[key] || nodeRoleLabelZh.descendant;
}

function resolveNodeYearText(node) {
  const raw = resolveNodeYear(node, timelineMetrics.value.fallbackYear);
  if (!Number.isFinite(raw)) return '-';
  return String(Math.round(raw));
}

function resolveNodePublicationDate(node) {
  const raw = textOrFallback(
    node?.publication_date
    ?? node?.published_at
    ?? node?.date
    ?? node?.published_date,
    ''
  );
  if (!raw) return '';
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toISOString().slice(0, 10);
}

function resolveNodeVenue(node) {
  return textOrFallback(
    node?.venue
    ?? node?.journal
    ?? node?.conference
    ?? node?.source
    ?? node?.publisher,
    '-'
  );
}

function resolveNodeAuthors(node) {
  const rawAuthors = node?.authors;
  if (Array.isArray(rawAuthors)) {
    const normalized = rawAuthors.map((item) => String(item || '').trim()).filter(Boolean);
    if (!normalized.length) return '-';
    if (normalized.length <= 4) return normalized.join(', ');
    return `${normalized.slice(0, 4).join(', ')} 等`;
  }
  return textOrFallback(rawAuthors, '-');
}

function resolveNodeUrl(node) {
  const raw = textOrFallback(
    node?.url
    ?? node?.paper_url
    ?? node?.pdf_url
    ?? node?.link
    ?? node?.source_url,
    ''
  );
  if (!raw) return '';
  if (/^https?:\/\//i.test(raw)) return raw;
  return '';
}

function normalizeYear(value) {
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return Math.round(numeric);
  }
  const matched = String(value || '').match(/(19|20)\d{2}/);
  if (!matched) return null;
  const parsed = Number(matched[0]);
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

function resolveRawNodeYear(node) {
  return normalizeYear(
    node?.year
    ?? node?.published_year
    ?? node?.publication_year
    ?? node?.published_at
    ?? node?.publication_date
  );
}

function resolveMedianYear(years) {
  if (!Array.isArray(years) || !years.length) return null;
  const sorted = [...years].sort((left, right) => left - right);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) {
    return sorted[mid];
  }
  return Math.round((sorted[mid - 1] + sorted[mid]) / 2);
}

function clamp(value, minValue, maxValue) {
  return Math.min(maxValue, Math.max(minValue, value));
}

function resolveTimelineTickStep(span, nodeCount) {
  if (span <= 1) return 1;
  if (span <= 18) return 1;
  if (nodeCount <= 20 && span <= 24) return 1;
  if (span <= 36) return 2;
  if (span <= 70) return 5;
  return 10;
}

function resolveEffectiveGap(count, desiredGap, topBound, bottomBound, minGap = 10) {
  if (count <= 1) return Math.max(minGap, desiredGap);
  const available = Math.max(0, bottomBound - topBound);
  const theoreticalMax = available / (count - 1);
  if (!Number.isFinite(theoreticalMax) || theoreticalMax <= 0) return minGap;
  return clamp(desiredGap, minGap, theoreticalMax);
}

function centeredBucketOffset(index, total) {
  if (total <= 1) return 0;
  return index - (total - 1) / 2;
}

function spreadNodesVertically(nodes, { minGap, topBound, bottomBound }) {
  if (!Array.isArray(nodes) || nodes.length < 2) return;
  const effectiveGap = resolveEffectiveGap(nodes.length, minGap, topBound, bottomBound, 8);
  const sorted = [...nodes].sort((a, b) => a.y - b.y);
  sorted[0].y = clamp(sorted[0].y, topBound, bottomBound);
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const current = sorted[index];
    current.y = Math.max(current.y, previous.y + effectiveGap);
  }
  for (let index = sorted.length - 2; index >= 0; index -= 1) {
    const next = sorted[index + 1];
    const current = sorted[index];
    current.y = Math.min(current.y, next.y - effectiveGap);
  }
  for (const node of sorted) {
    node.y = clamp(node.y, topBound, bottomBound);
  }
}

function spreadNodeLabels(nodes, { minGap, topBound, bottomBound }) {
  if (!Array.isArray(nodes) || !nodes.length) return;
  const effectiveGap = resolveEffectiveGap(nodes.length, minGap, topBound, bottomBound, 9);
  const sorted = [...nodes].sort((a, b) => a.y - b.y);
  for (const node of sorted) {
    node.labelY = node.y + node.radius + 15;
  }
  sorted[0].labelY = clamp(sorted[0].labelY, topBound, bottomBound);
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const current = sorted[index];
    current.labelY = Math.max(current.labelY, previous.labelY + effectiveGap);
  }
  for (let index = sorted.length - 2; index >= 0; index -= 1) {
    const next = sorted[index + 1];
    const current = sorted[index];
    current.labelY = Math.min(current.labelY, next.labelY - effectiveGap);
  }
  for (const node of sorted) {
    const safeLabelY = clamp(node.labelY, topBound, bottomBound);
    node.labelDy = safeLabelY - node.y;
    node.labelY = safeLabelY;
  }
}

function spreadSideNodesByGeneration(
  nodes,
  {
    nodeMinGap,
    topBound,
    bottomBound
  }
) {
  if (!Array.isArray(nodes) || !nodes.length) return;
  const generationGroups = new Map();
  for (const node of nodes) {
    const key = Number.isFinite(Number(node?.generation)) ? Number(node.generation) : 1;
    if (!generationGroups.has(key)) {
      generationGroups.set(key, []);
    }
    generationGroups.get(key).push(node);
  }
  for (const groupNodes of generationGroups.values()) {
    spreadNodesVertically(groupNodes, {
      minGap: nodeMinGap,
      topBound,
      bottomBound
    });
  }
}

function clampNodeCenter(value, node, topBound, bottomBound) {
  const nodeRadius = Number.isFinite(Number(node?.radius)) ? Number(node.radius) : 0;
  const minY = topBound + nodeRadius + 2;
  const maxY = bottomBound - nodeRadius - 2;
  if (minY > maxY) {
    return (minY + maxY) / 2;
  }
  return clamp(value, minY, maxY);
}

function enforceNodeCircleSeparation(nodes, { topBound, bottomBound, padding }) {
  if (!Array.isArray(nodes) || nodes.length < 2) return;
  const sorted = [...nodes].sort((left, right) => left.y - right.y);
  const collisionPadding = Math.max(0, Number(padding) || 0);

  for (const node of sorted) {
    node.y = clampNodeCenter(node.y, node, topBound, bottomBound);
  }

  for (let pass = 0; pass < 2; pass += 1) {
    for (let index = 1; index < sorted.length; index += 1) {
      const previous = sorted[index - 1];
      const current = sorted[index];
      const requiredGap = Math.max(
        0,
        (Number(previous.radius) || 0) + (Number(current.radius) || 0) + collisionPadding
      );
      const minY = previous.y + requiredGap;
      if (current.y < minY) {
        current.y = minY;
      }
      current.y = clampNodeCenter(current.y, current, topBound, bottomBound);
    }

    for (let index = sorted.length - 2; index >= 0; index -= 1) {
      const next = sorted[index + 1];
      const current = sorted[index];
      const requiredGap = Math.max(
        0,
        (Number(next.radius) || 0) + (Number(current.radius) || 0) + collisionPadding
      );
      const maxY = next.y - requiredGap;
      if (current.y > maxY) {
        current.y = maxY;
      }
      current.y = clampNodeCenter(current.y, current, topBound, bottomBound);
    }
  }
}

function getNodeOffset(nodeId) {
  const key = String(nodeId || '').trim();
  if (!key) return { x: 0, y: 0 };
  const raw = nodeOffsetMap.value[key];
  if (!raw) return { x: 0, y: 0 };
  return {
    x: Number.isFinite(Number(raw?.x)) ? Number(raw.x) : 0,
    y: Number.isFinite(Number(raw?.y)) ? Number(raw.y) : 0
  };
}

const rootPaper = computed(() => {
  return props.lineage?.root || props.lineage?.root_paper || {};
});

const isCanvasDragging = computed(() => {
  return Boolean(panState.value.active || nodeDragState.value.active);
});

const draggingNodeId = computed(() => String(nodeDragState.value.nodeId || '').trim());
const fullscreenButtonLabel = computed(() => (isFullscreen.value ? '收回' : '全屏'));

const canvasViewportTransform = computed(() => {
  const { x, y, scale } = viewport.value;
  if (props.stretchTimeline) {
    return `translate(0 ${y}) scale(${scale})`;
  }
  return `translate(${x} ${y}) scale(${scale})`;
});

const timelineViewportStyle = computed(() => {
  if (props.stretchTimeline) {
    return {
      transform: 'none',
      transformOrigin: '0 0'
    };
  }
  const { x, scale } = viewport.value;
  return {
    transform: `translateX(${x}px) scaleX(${scale})`,
    transformOrigin: '0 0'
  };
});

const normalizedNodes = computed(() => {
  const root = rootPaper.value || {};
  const ancestors = Array.isArray(props.lineage?.ancestors) ? props.lineage.ancestors : [];
  const descendants = Array.isArray(props.lineage?.descendants) ? props.lineage.descendants : [];
  const rootId = resolvePaperId(root) || 'root';

  const rootNode = {
    ...root,
    id: rootId,
    paper_id: rootId,
    nodeType: 'root',
    abstract: root?.abstract || '',
    citation_count: normalizeCitationCount(root?.citation_count || root?.citationCount),
    relation_type: 'mentioning',
    relation_description: '种子论文',
    generation: 0
  };
  const ancestorNodes = ancestors.map((item, index) => ({
    ...item,
    id: resolvePaperId(item) || `ancestor-${index}`,
    paper_id: resolvePaperId(item) || `ancestor-${index}`,
    abstract: item?.abstract || '',
    nodeType: 'ancestor'
  }));
  const descendantNodes = descendants.map((item, index) => ({
    ...item,
    id: resolvePaperId(item) || `descendant-${index}`,
    paper_id: resolvePaperId(item) || `descendant-${index}`,
    abstract: item?.abstract || '',
    nodeType: 'descendant'
  }));

  return [rootNode, ...ancestorNodes, ...descendantNodes];
});

const nodeYearContext = computed(() => {
  const nodes = normalizedNodes.value;
  const currentYear = new Date().getFullYear();
  const statsRange = Array.isArray(props.lineage?.stats?.year_range) ? props.lineage.stats.year_range : [];
  const statsMinYear = normalizeYear(statsRange?.[0]);
  const statsMaxYear = normalizeYear(statsRange?.[1]);
  const rawRootYear = resolveRawNodeYear(rootPaper.value);
  const knownYears = nodes
    .map((node) => resolveRawNodeYear(node))
    .filter((year) => Number.isFinite(year))
    .map((year) => clamp(Math.round(year), YEAR_MIN_BOUND, currentYear + YEAR_MAX_FUTURE_OFFSET));

  let baseYear = Number.isFinite(rawRootYear)
    ? rawRootYear
    : resolveMedianYear(knownYears);
  if (!Number.isFinite(baseYear)) {
    if (Number.isFinite(statsMinYear) && Number.isFinite(statsMaxYear)) {
      baseYear = Math.round((statsMinYear + statsMaxYear) / 2);
    } else if (Number.isFinite(statsMinYear)) {
      baseYear = statsMinYear;
    } else if (Number.isFinite(statsMaxYear)) {
      baseYear = statsMaxYear;
    } else {
      baseYear = currentYear;
    }
  }
  baseYear = clamp(Math.round(baseYear), YEAR_MIN_BOUND, currentYear + YEAR_MAX_FUTURE_OFFSET);

  const minKnownYear = knownYears.length ? Math.min(...knownYears) : null;
  const maxKnownYear = knownYears.length ? Math.max(...knownYears) : null;
  const knownSpan = Number.isFinite(minKnownYear) && Number.isFinite(maxKnownYear)
    ? Math.max(1, maxKnownYear - minKnownYear)
    : 1;
  const knownPadding = Math.max(1, Math.min(4, Math.ceil(knownSpan / 8)));
  const inferredMinBound = Number.isFinite(minKnownYear) ? minKnownYear - knownPadding : baseYear - 12;
  const inferredMaxBound = Number.isFinite(maxKnownYear) ? maxKnownYear + knownPadding : baseYear + 12;
  const yearByNodeId = new Map();
  const resolvedYears = [];

  for (const node of nodes) {
    const nodeId = resolvePaperId(node) || String(node?.id || '').trim();
    const rawYear = resolveRawNodeYear(node);
    let resolvedYear = rawYear;
    if (!Number.isFinite(resolvedYear)) {
      const generation = Math.max(1, normalizeGeneration(node?.hop ?? node?.generation ?? 1));
      if (node?.nodeType === 'ancestor') {
        resolvedYear = baseYear - generation;
      } else if (node?.nodeType === 'descendant') {
        resolvedYear = baseYear + generation;
      } else {
        resolvedYear = baseYear;
      }
    }
    resolvedYear = clamp(Math.round(resolvedYear), inferredMinBound, inferredMaxBound);
    resolvedYear = clamp(resolvedYear, YEAR_MIN_BOUND, currentYear + YEAR_MAX_FUTURE_OFFSET);
    resolvedYears.push(resolvedYear);
    if (nodeId) {
      yearByNodeId.set(nodeId, resolvedYear);
    }
    if (node?.paper_id) {
      yearByNodeId.set(String(node.paper_id), resolvedYear);
    }
    if (node?.id) {
      yearByNodeId.set(String(node.id), resolvedYear);
    }
  }

  const uniqueYears = [...new Set(resolvedYears)].sort((left, right) => left - right);

  return {
    baseYear,
    yearByNodeId,
    resolvedYears,
    uniqueYears
  };
});

function resolveNodeYear(node, fallbackYear) {
  const nodeId = resolvePaperId(node) || String(node?.id || '').trim();
  if (nodeId && nodeYearContext.value.yearByNodeId.has(nodeId)) {
    return nodeYearContext.value.yearByNodeId.get(nodeId);
  }
  const rawYear = resolveRawNodeYear(node);
  if (Number.isFinite(rawYear)) return rawYear;
  if (Number.isFinite(fallbackYear)) return Math.round(fallbackYear);
  return nodeYearContext.value.baseYear;
}

const timelineMetrics = computed(() => {
  const width = Math.max(320, Number(viewBox.value.width || 0));
  const stretchedPadding = clamp(
    Math.round(width * STRETCHED_TIMELINE_SIDE_RATIO),
    STRETCHED_TIMELINE_SIDE_MIN,
    STRETCHED_TIMELINE_SIDE_MAX
  );
  const leftPadding = props.stretchTimeline
    ? stretchedPadding
    : Math.round(width * TIMELINE_LEFT_RATIO);
  const rightPadding = props.stretchTimeline
    ? stretchedPadding
    : Math.round(width * TIMELINE_RIGHT_RATIO);
  const axisWidth = Math.max(120, width - leftPadding - rightPadding);

  const context = nodeYearContext.value;
  const years = context.uniqueYears.length ? context.uniqueYears : [context.baseYear];
  const minRaw = years.length ? years[0] : context.baseYear;
  const maxRaw = years.length ? years[years.length - 1] : context.baseYear;
  const rawSpan = Math.max(1, maxRaw - minRaw);
  const density = years.length / Math.max(1, rawSpan + 1);
  const useSparseAxis = (
    years.length >= 2
    && rawSpan >= SPARSE_TIMELINE_MIN_SPAN
    && density <= SPARSE_TIMELINE_DENSITY_THRESHOLD
  );

  let axisYears = [];
  if (useSparseAxis) {
    axisYears = [...years];
  } else {
    const step = resolveTimelineTickStep(rawSpan, Math.max(1, years.length));
    let minYear = Math.floor(minRaw / step) * step;
    let maxYear = Math.ceil(maxRaw / step) * step;
    if (minYear === maxYear) {
      maxYear = minYear + step;
    }
    for (let year = minYear; year <= maxYear; year += step) {
      axisYears.push(year);
    }
  }

  if (!axisYears.length) {
    axisYears = [context.baseYear - 1, context.baseYear, context.baseYear + 1];
  } else if (axisYears.length === 1) {
    axisYears = [axisYears[0] - 1, axisYears[0], axisYears[0] + 1];
  }

  const intervalCount = Math.max(1, axisYears.length - 1);
  const ticks = axisYears.map((year, index) => {
    const ratio = index / intervalCount;
    return {
      year,
      x: leftPadding + ratio * axisWidth
    };
  });

  return {
    minYear: axisYears[0],
    maxYear: axisYears[axisYears.length - 1],
    span: Math.max(1, axisYears[axisYears.length - 1] - axisYears[0]),
    intervalCount,
    axisYears,
    leftPadding,
    axisWidth,
    fallbackYear: context.baseYear,
    ticks
  };
});

const yearTicks = computed(() => timelineMetrics.value.ticks);

function yearToX(yearValue) {
  const metrics = timelineMetrics.value;
  const axisYears = metrics.axisYears;
  const ticks = metrics.ticks;
  const year = Number.isFinite(Number(yearValue)) ? Number(yearValue) : metrics.fallbackYear;
  if (!axisYears.length || !ticks.length) {
    return metrics.leftPadding;
  }
  if (axisYears.length === 1) {
    return ticks[0].x;
  }
  if (year <= axisYears[0]) {
    return ticks[0].x;
  }
  const lastIndex = axisYears.length - 1;
  if (year >= axisYears[lastIndex]) {
    return ticks[lastIndex].x;
  }
  for (let index = 0; index < lastIndex; index += 1) {
    const leftYear = axisYears[index];
    const rightYear = axisYears[index + 1];
    if (year > rightYear) continue;
    const leftX = ticks[index].x;
    const rightX = ticks[index + 1].x;
    const segmentSpan = rightYear - leftYear;
    if (!Number.isFinite(segmentSpan) || segmentSpan <= 0) {
      return leftX;
    }
    const ratio = clamp((year - leftYear) / segmentSpan, 0, 1);
    return leftX + (rightX - leftX) * ratio;
  }
  return ticks[lastIndex].x;
}

function computeRadius(node, isRoot = false) {
  if (isRoot) return 30;
  const citations = normalizeCitationCount(node?.citation_count || node?.citationCount);
  const normalized = Math.min(citations / 50000, 1);
  return 13 + normalized * 8;
}

function relationWeight(type) {
  const key = String(type || '').trim().toLowerCase();
  if (key === 'extending') return 0.88;
  if (key === 'supporting') return 0.8;
  if (key === 'migrating') return 0.7;
  if (key === 'contradicting') return 0.62;
  return 0.52;
}

function shortTitle(title) {
  const text = String(title || '').trim();
  if (text.length <= 24) return text;
  return `${text.slice(0, 23)}...`;
}

const layoutNodes = computed(() => {
  const width = viewBox.value.width;
  const height = viewBox.value.height;
  const nodes = normalizedNodes.value;
  if (!nodes.length) return [];
  const stretchScale = props.stretchTimeline
    ? Math.max(VIEWPORT_ABSOLUTE_MIN_SCALE, Number(viewport.value.scale || 1))
    : 1;
  const stretchInverseScale = 1 / stretchScale;

  const compact = width <= 768;
  const spacing = compact ? LAYOUT_SPACING.compact : LAYOUT_SPACING.regular;
  const headHeight = compact ? 30 : 32;
  const axisHeight = compact ? 24 : 28;
  const layoutTopInset = 10 + headHeight + axisHeight + 10;
  const layoutBottomInset = compact ? 14 : 16;
  const minPlotHeight = compact ? 260 : 340;
  let topBound = Math.max(36, layoutTopInset);
  let bottomBound = Math.max(topBound + minPlotHeight, height - layoutBottomInset);
  if (bottomBound > height - 8) {
    bottomBound = height - 8;
  }
  if (bottomBound - topBound < minPlotHeight) {
    topBound = Math.max(24, bottomBound - minPlotHeight);
  }

  const centerY = topBound + (bottomBound - topBound) / 2;
  const bandGap = spacing.centerBandGap;
  let ancestorTopBound = topBound;
  let ancestorBottomBound = Math.max(ancestorTopBound + (compact ? 92 : 120), centerY - bandGap);
  let descendantTopBound = Math.min(bottomBound - (compact ? 92 : 120), centerY + bandGap);
  const descendantBottomBound = bottomBound;
  if (ancestorBottomBound >= descendantTopBound) {
    ancestorBottomBound = centerY - 22;
    descendantTopBound = centerY + 22;
  }

  const root = nodes[0];
  const ancestors = nodes.filter((node) => node.nodeType === 'ancestor');
  const descendants = nodes.filter((node) => node.nodeType === 'descendant');
  const yearBandWidth = Math.max(18, timelineMetrics.value.axisWidth / Math.max(1, timelineMetrics.value.intervalCount));
  const fallbackYear = timelineMetrics.value.fallbackYear;
  const rootYear = resolveNodeYear(root, fallbackYear) || fallbackYear;

  const output = [];
  output.push({
    ...root,
    x: yearToX(rootYear) * stretchInverseScale,
    y: centerY,
    radius: computeRadius(root, true),
    fill: 'var(--text)',
    stroke: 'var(--text)',
    strokeWidth: 1.6,
    yearFill: 'var(--bg)',
    citationFill: 'var(--panel)',
    yearText: Number.isFinite(rootYear) ? String(rootYear) : '--',
    citationText: formatCitation(root?.citation_count),
    shortTitle: 'Seed Paper',
    labelDy: compact ? 42 : 46
  });

  const buildSideNodes = (items, nodeType) => {
    if (!items.length) return [];
    const sideSorted = [...items].sort((left, right) => {
      const leftYear = resolveNodeYear(left, fallbackYear) || fallbackYear;
      const rightYear = resolveNodeYear(right, fallbackYear) || fallbackYear;
      if (leftYear !== rightYear) {
        return leftYear - rightYear;
      }
      const leftCitation = normalizeCitationCount(left?.citation_count || left?.citationCount);
      const rightCitation = normalizeCitationCount(right?.citation_count || right?.citationCount);
      if (leftCitation !== rightCitation) {
        return rightCitation - leftCitation;
      }
      return String(left?.title || '').localeCompare(String(right?.title || ''));
    });

    const yearCounts = new Map();
    for (const item of sideSorted) {
      const itemYear = resolveNodeYear(item, fallbackYear) || fallbackYear;
      yearCounts.set(itemYear, (yearCounts.get(itemYear) || 0) + 1);
    }
    const orderedYears = [...yearCounts.keys()].sort((left, right) => left - right);
    const yearOrder = new Map();
    orderedYears.forEach((year, index) => {
      yearOrder.set(year, index);
    });
    const totalYearBuckets = Math.max(1, orderedYears.length);
    const laneGapX = Math.min(compact ? 16 : 22, Math.max(9, yearBandWidth * 0.22));
    const maxHorizontalSpread = Math.max(12, yearBandWidth * 0.36);
    const computedMaxColumnsByWidth = Math.max(
      1,
      Math.floor((maxHorizontalSpread * 2 + laneGapX) / laneGapX)
    );
    const maxColumnsPerYear = Math.max(
      1,
      Math.min(spacing.maxColumnsPerYear, computedMaxColumnsByWidth)
    );
    const yearLayouts = new Map();
    for (const [year, count] of yearCounts.entries()) {
      const columns = Math.max(1, Math.min(count, maxColumnsPerYear));
      const rows = Math.max(1, Math.ceil(count / columns));
      yearLayouts.set(year, {
        columns,
        rows,
        index: 0
      });
    }

    const sideNodes = sideSorted.map((item) => {
      const relationType = normalizeCitationType(item?.ctype || item?.relation_type);
      const relationRelevance = relationWeight(relationType);
      const generation = normalizeGeneration(item?.hop || item?.generation || 1);
      const color = citationConfig[relationType]?.color || citationConfig.mentioning.color;
      const nodeYear = resolveNodeYear(item, fallbackYear);
      const year = Number.isFinite(nodeYear) ? nodeYear : fallbackYear;
      const yearLayout = yearLayouts.get(year) || { columns: 1, rows: 1, index: 0 };
      const slot = yearLayout.index;
      yearLayout.index += 1;
      const colIndex = slot % yearLayout.columns;
      const rowIndex = Math.floor(slot / yearLayout.columns);
      const xSpreadOffset = clamp(
        centeredBucketOffset(colIndex, yearLayout.columns) * laneGapX,
        -maxHorizontalSpread,
        maxHorizontalSpread
      );
      const yearBucketOffset = centeredBucketOffset(
        yearOrder.get(year) ?? 0,
        totalYearBuckets
      ) * spacing.yearLaneGap;
      const ySpreadOffset = centeredBucketOffset(rowIndex, yearLayout.rows) * spacing.yearRowGap;
      const verticalBaseGap = spacing.generationGap;
      const relevanceShift = (1 - relationRelevance) * spacing.relevanceShift;
      const baseY = nodeType === 'ancestor'
        ? centerY - generation * verticalBaseGap - relevanceShift + ySpreadOffset + yearBucketOffset
        : centerY + generation * verticalBaseGap + relevanceShift + ySpreadOffset + yearBucketOffset;

      return {
        ...item,
        relation_type: relationType,
        generation,
        citation_count: normalizeCitationCount(item?.citation_count || item?.citationCount),
        x: (yearToX(year) + xSpreadOffset) * stretchInverseScale,
        y: baseY,
        radius: computeRadius(item),
        fill: 'var(--bg)',
        stroke: color,
        strokeWidth: 1.5,
        yearFill: 'var(--text)',
        citationFill: 'var(--muted)',
        yearText: Number.isFinite(year) ? String(year) : '--',
        citationText: formatCitation(item?.citation_count),
        shortTitle: shortTitle(item?.title),
        labelDy: 0
      };
    });

    if (nodeType === 'ancestor') {
      const overflowExpansion = Math.max(
        spacing.generationGap,
        spacing.nodeMinGap * Math.max(2, Math.ceil(sideNodes.length / 2))
      );
      const expandedTopBound = ancestorTopBound - overflowExpansion;
      const expandedBottomBound = ancestorBottomBound + overflowExpansion;
      spreadSideNodesByGeneration(sideNodes, {
        nodeMinGap: spacing.nodeMinGap,
        topBound: expandedTopBound,
        bottomBound: expandedBottomBound
      });
      enforceNodeCircleSeparation(sideNodes, {
        topBound: expandedTopBound,
        bottomBound: expandedBottomBound,
        padding: spacing.nodeCollisionPadding
      });
      spreadNodeLabels(sideNodes, {
        minGap: spacing.labelMinGap,
        topBound: expandedTopBound + 14,
        bottomBound: expandedBottomBound + 26
      });
      return sideNodes;
    }

    const overflowExpansion = Math.max(
      spacing.generationGap,
      spacing.nodeMinGap * Math.max(2, Math.ceil(sideNodes.length / 2))
    );
    const expandedTopBound = descendantTopBound - overflowExpansion;
    const expandedBottomBound = descendantBottomBound + overflowExpansion;
    spreadSideNodesByGeneration(sideNodes, {
      nodeMinGap: spacing.nodeMinGap,
      topBound: expandedTopBound,
      bottomBound: expandedBottomBound
    });
    enforceNodeCircleSeparation(sideNodes, {
      topBound: expandedTopBound,
      bottomBound: expandedBottomBound,
      padding: spacing.nodeCollisionPadding
    });
    const descendantLabelGap = Math.round(spacing.labelMinGap * DESCENDANT_LABEL_GAP_BOOST);
    spreadNodeLabels(sideNodes, {
      minGap: descendantLabelGap,
      topBound: expandedTopBound + 14,
      bottomBound: expandedBottomBound + DESCENDANT_LABEL_BOTTOM_EXTRA
    });
    return sideNodes;
  };

  output.push(...buildSideNodes(ancestors, 'ancestor'));
  output.push(...buildSideNodes(descendants, 'descendant'));

  for (const node of output) {
    const offset = getNodeOffset(node.id);
    const safeOffsetX = props.stretchTimeline ? 0 : offset.x;
    const safeOffsetY = offset.y;
    if (!safeOffsetX && !safeOffsetY) continue;
    node.x += safeOffsetX;
    node.y += safeOffsetY;
  }

  return output;
});

const layoutEdges = computed(() => {
  const nodeMap = new Map();
  for (const node of layoutNodes.value) {
    nodeMap.set(node.id, node);
    if (node?.paper_id) {
      nodeMap.set(String(node.paper_id), node);
    }
  }
  const result = [];
  const rawEdges = Array.isArray(props.lineage?.edges) ? props.lineage.edges : [];
  if (rawEdges.length) {
    rawEdges.forEach((edge, index) => {
      const sourceNode = nodeMap.get(String(edge?.source || '').trim());
      const targetNode = nodeMap.get(String(edge?.target || '').trim());
      if (!sourceNode || !targetNode) return;
      const citationType = normalizeCitationType(edge?.ctype);
      const color = citationConfig[citationType]?.color || citationConfig.mentioning.color;
      result.push({
        id: `edge-explicit-${index}-${sourceNode.id}-${targetNode.id}`,
        citationType,
        color,
        strokeWidth: citationType === 'mentioning' ? 1.35 : 1.6,
        opacity: citationType === 'mentioning' ? 0.62 : 0.66,
        path: bezierPath(sourceNode.x, sourceNode.y, targetNode.x, targetNode.y)
      });
    });
    if (result.length) return result;
  }

  const rootNode = layoutNodes.value.find((node) => node.nodeType === 'root');
  for (const node of layoutNodes.value) {
    if (node.nodeType === 'root' || !rootNode) continue;
    const sourceNode = node.nodeType === 'ancestor' ? rootNode : node;
    const targetNode = node.nodeType === 'ancestor' ? node : rootNode;
    const citationType = normalizeCitationType(node?.ctype || node?.relation_type);
    const color = citationConfig[citationType]?.color || citationConfig.mentioning.color;
    result.push({
      id: `edge-${sourceNode.id}-${targetNode.id}`,
      citationType,
      color,
      strokeWidth: citationType === 'mentioning' ? 1.35 : 1.6,
      opacity: citationType === 'mentioning' ? 0.62 : 0.66,
      path: bezierPath(sourceNode.x, sourceNode.y, targetNode.x, targetNode.y)
    });
  }
  return result;
});

const layoutContentBounds = computed(() => {
  const nodes = layoutNodes.value;
  if (!Array.isArray(nodes) || !nodes.length) {
    return null;
  }

  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  for (const node of nodes) {
    const radius = Math.max(8, Number(node?.radius || 0));
    const labelDy = Number.isFinite(Number(node?.labelDy)) ? Number(node.labelDy) : 0;
    const title = String(node?.shortTitle || node?.title || '');
    const labelHalfWidth = clamp(14 + title.length * 3.2, 48, 142);

    const nodeMinX = node.x - Math.max(radius + 8, labelHalfWidth);
    const nodeMaxX = node.x + Math.max(radius + 8, labelHalfWidth);
    const nodeMinY = Math.min(node.y - radius - 10, node.y + labelDy - 12);
    const nodeMaxY = Math.max(node.y + radius + 10, node.y + labelDy + 6);

    minX = Math.min(minX, nodeMinX);
    maxX = Math.max(maxX, nodeMaxX);
    minY = Math.min(minY, nodeMinY);
    maxY = Math.max(maxY, nodeMaxY);
  }

  if (!Number.isFinite(minX) || !Number.isFinite(maxX) || !Number.isFinite(minY) || !Number.isFinite(maxY)) {
    return null;
  }

  return {
    minX,
    maxX,
    minY,
    maxY,
    width: Math.max(1, maxX - minX),
    height: Math.max(1, maxY - minY)
  };
});

const viewportScaleRange = computed(() => {
  let minScale = VIEWPORT_DEFAULT_MIN_SCALE;
  const bounds = layoutContentBounds.value;

  if (bounds) {
    const safeWidth = Math.max(160, Number(viewBox.value.width || 0) - VIEWPORT_FIT_PADDING * 2);
    const safeHeight = Math.max(160, Number(viewBox.value.height || 0) - VIEWPORT_FIT_PADDING * 2);
    const fitScaleX = safeWidth / bounds.width;
    const fitScaleY = safeHeight / bounds.height;
    const fitScale = props.stretchTimeline ? fitScaleY : Math.min(fitScaleX, fitScaleY);
    if (Number.isFinite(fitScale) && fitScale > 0) {
      minScale = Math.min(VIEWPORT_DEFAULT_MIN_SCALE, fitScale * 0.9);
    }
  }

  minScale = clamp(minScale, VIEWPORT_ABSOLUTE_MIN_SCALE, VIEWPORT_MAX_SCALE);
  return {
    min: minScale,
    max: VIEWPORT_MAX_SCALE
  };
});

const detailMeta = computed(() => {
  if (!selectedNode.value) return '';
  const selected = selectedNode.value;
  const year = resolveNodeYearText(selected);
  const cite = formatCitation(normalizeCitationCount(selected?.citation_count || selected?.citationCount));
  if (String(selected?.nodeType || '').toLowerCase() === 'root') {
    return `${year} · ${cite} 引 · ${resolveNodeRoleLabel(selected)}`;
  }
  return `${year} · ${cite} 引 · ${resolveCitationTypeLabel(selected?.ctype || selected?.relation_type)}`;
});

const selectedNodeInfo = computed(() => {
  const selected = selectedNode.value;
  if (!selected) {
    return {
      nodeRoleLabel: nodeRoleLabelZh.root,
      relationLabel: '',
      abstractText: '暂无摘要信息。',
      relationDescription: '',
      paperId: '-',
      url: '',
      metaItems: []
    };
  }

  const publicationDate = resolveNodePublicationDate(selected);
  const yearText = resolveNodeYearText(selected);
  const citationCount = formatCitation(normalizeCitationCount(selected?.citation_count || selected?.citationCount));
  const venue = resolveNodeVenue(selected);
  const authors = resolveNodeAuthors(selected);
  const relationLabel = String(selected?.nodeType || '').toLowerCase() === 'root'
    ? ''
    : resolveCitationTypeLabel(selected?.ctype || selected?.relation_type);
  const relationDescription = textOrFallback(selected?.relation_description, '');
  const abstractText = textOrFallback(selected?.abstract, '暂无摘要信息。');
  const paperId = resolvePaperId(selected) || textOrFallback(selected?.id, '-');
  const metaItems = [
    { label: '论文 ID', value: paperId },
    { label: '发表年份', value: yearText },
    { label: '发表日期', value: publicationDate || '-' },
    { label: '引用次数', value: citationCount },
    { label: '期刊/会议', value: venue },
    { label: '作者', value: authors }
  ];

  return {
    nodeRoleLabel: resolveNodeRoleLabel(selected),
    relationLabel,
    relationDescription,
    abstractText,
    paperId,
    url: resolveNodeUrl(selected),
    metaItems
  };
});

function formatCitation(value) {
  const count = Number(value || 0);
  if (!Number.isFinite(count) || count <= 0) return '0';
  if (count >= 1000) return `${Math.round(count / 1000)}k`;
  return String(Math.round(count));
}

function buildNodeTooltipMeta(node) {
  const year = resolveNodeYearText(node);
  const cite = formatCitation(normalizeCitationCount(node?.citation_count || node?.citationCount));
  const role = resolveNodeRoleLabel(node);
  if (String(node?.nodeType || '').toLowerCase() === 'root') {
    return `${role} · ${year} · ${cite} 引`;
  }
  const relation = resolveCitationTypeLabel(node?.ctype || node?.relation_type);
  return `${role} · ${year} · ${cite} 引 · ${relation}`;
}

function bezierPath(x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const c1x = x1 + dx * 0.4 + dy * 0.12;
  const c1y = y1 + dy * 0.4 - dx * 0.12;
  const c2x = x1 + dx * 0.6 + dy * 0.12;
  const c2y = y1 + dy * 0.6 - dx * 0.12;
  return `M${x1},${y1} C${c1x},${c1y} ${c2x},${c2y} ${x2},${y2}`;
}

function resolveCanvasMetrics() {
  if (!canvasRef.value) {
    return {
      left: 0,
      top: 0,
      xRatio: 1,
      yRatio: 1
    };
  }
  const rect = canvasRef.value.getBoundingClientRect();
  return {
    left: rect.left,
    top: rect.top,
    xRatio: rect.width > 0 ? viewBox.value.width / rect.width : 1,
    yRatio: rect.height > 0 ? viewBox.value.height / rect.height : 1
  };
}

function getPointerCoordinates(event, metrics = null) {
  const safeMetrics = metrics || resolveCanvasMetrics();
  return {
    x: (event.clientX - safeMetrics.left) * safeMetrics.xRatio,
    y: (event.clientY - safeMetrics.top) * safeMetrics.yRatio
  };
}

function normalizeWheelDelta(event) {
  let delta = Number(event.deltaY || 0);
  if (!Number.isFinite(delta)) return 0;
  if (event.deltaMode === 1) {
    delta *= 16;
  } else if (event.deltaMode === 2) {
    delta *= Math.max(220, viewBox.value.height);
  }
  return delta;
}

function resolveWheelZoomSensitivity(absDelta, event) {
  let sensitivity = WHEEL_ZOOM_SENSITIVITY.extreme;
  if (absDelta <= 4) {
    sensitivity = WHEEL_ZOOM_SENSITIVITY.tiny;
  } else if (absDelta <= 12) {
    sensitivity = WHEEL_ZOOM_SENSITIVITY.small;
  } else if (absDelta <= 28) {
    sensitivity = WHEEL_ZOOM_SENSITIVITY.medium;
  } else if (absDelta <= 60) {
    sensitivity = WHEEL_ZOOM_SENSITIVITY.large;
  } else if (absDelta <= 120) {
    sensitivity = WHEEL_ZOOM_SENSITIVITY.huge;
  }
  if (event.ctrlKey || event.metaKey) {
    sensitivity *= 1.25;
  }
  return sensitivity;
}

function getNodeDragOffset(nodeId) {
  const resolved = getNodeOffset(nodeId);
  return {
    x: resolved.x,
    y: resolved.y
  };
}

function setNodeDragOffset(nodeId, nextOffset) {
  const key = String(nodeId || '').trim();
  if (!key) return;
  nodeOffsetMap.value = {
    ...nodeOffsetMap.value,
    [key]: {
      x: Number.isFinite(Number(nextOffset?.x)) ? Number(nextOffset.x) : 0,
      y: Number.isFinite(Number(nextOffset?.y)) ? Number(nextOffset.y) : 0
    }
  };
}

function normalizeScale(value) {
  const limits = viewportScaleRange.value;
  return clamp(value, limits.min, limits.max);
}

function buildCenteredViewport(scaleValue) {
  const nextScale = normalizeScale(scaleValue);
  const bounds = layoutContentBounds.value;
  if (!bounds) {
    return {
      x: 0,
      y: 0,
      scale: nextScale
    };
  }
  if (props.stretchTimeline) {
    return {
      x: 0,
      y: (viewBox.value.height - bounds.height * nextScale) / 2 - bounds.minY * nextScale,
      scale: nextScale
    };
  }
  return {
    x: (viewBox.value.width - bounds.width * nextScale) / 2 - bounds.minX * nextScale,
    y: (viewBox.value.height - bounds.height * nextScale) / 2 - bounds.minY * nextScale,
    scale: nextScale
  };
}

function clampViewportScaleAroundCenter() {
  const current = viewport.value;
  const nextScale = normalizeScale(current.scale);
  if (props.stretchTimeline && current.x !== 0) {
    current.x = 0;
  }
  if (Math.abs(nextScale - current.scale) < 0.0001) return;
  if (props.stretchTimeline) {
    const anchorY = viewBox.value.height / 2;
    const ratio = nextScale / current.scale;
    current.scale = nextScale;
    current.x = 0;
    current.y = anchorY - (anchorY - current.y) * ratio;
    return;
  }
  const anchor = {
    x: viewBox.value.width / 2,
    y: viewBox.value.height / 2
  };
  const ratio = nextScale / current.scale;
  current.scale = nextScale;
  current.x = anchor.x - (anchor.x - current.x) * ratio;
  current.y = anchor.y - (anchor.y - current.y) * ratio;
}

function clearPanState() {
  panState.value = {
    active: false,
    pointerId: null,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
    metrics: null
  };
}

function clearNodeDragState() {
  nodeDragState.value = {
    active: false,
    pointerId: null,
    nodeId: '',
    node: null,
    startX: 0,
    startY: 0,
    originOffsetX: 0,
    originOffsetY: 0,
    moved: false,
    metrics: null
  };
}

function releasePointerCapture(pointerId) {
  const safePointerId = Number(pointerId);
  if (!canvasRef.value || !Number.isInteger(safePointerId)) return;
  try {
    if (canvasRef.value.hasPointerCapture?.(safePointerId)) {
      canvasRef.value.releasePointerCapture(safePointerId);
    }
  } catch {
    // ignore pointer capture release errors
  }
}

function handleCanvasWheel(event) {
  const pointer = getPointerCoordinates(event);
  const currentScale = viewport.value.scale;
  const currentY = viewport.value.y;
  const currentX = viewport.value.x;
  const wheelDelta = normalizeWheelDelta(event);
  if (!Number.isFinite(wheelDelta) || wheelDelta === 0) return;
  const boundedDelta = clamp(wheelDelta, -WHEEL_DELTA_LIMIT, WHEEL_DELTA_LIMIT);
  if (Math.abs(boundedDelta) < WHEEL_MIN_EFFECT_DELTA) return;
  const sensitivity = resolveWheelZoomSensitivity(Math.abs(boundedDelta), event);
  const scaleFactor = Math.exp(-boundedDelta * sensitivity);
  const nextScale = normalizeScale(currentScale * scaleFactor);
  if (Math.abs(nextScale - currentScale) < 0.0001) return;
  const ratio = nextScale / currentScale;
  viewport.value.scale = nextScale;
  if (props.stretchTimeline) {
    viewport.value.x = 0;
    viewport.value.y = pointer.y - (pointer.y - currentY) * ratio;
    return;
  }
  viewport.value.x = pointer.x - (pointer.x - currentX) * ratio;
  viewport.value.y = pointer.y - (pointer.y - currentY) * ratio;
}

function handleCanvasPointerDown(event) {
  if (nodeDragState.value.active) return;
  if (event.pointerType === 'mouse' && event.button !== 0) return;
  const metrics = resolveCanvasMetrics();
  const pointer = getPointerCoordinates(event, metrics);
  panState.value = {
    active: true,
    pointerId: event.pointerId,
    startX: pointer.x,
    startY: pointer.y,
    originX: props.stretchTimeline ? 0 : viewport.value.x,
    originY: viewport.value.y,
    metrics
  };
  canvasRef.value?.setPointerCapture?.(event.pointerId);
}

function handleCanvasPointerMove(event) {
  if (nodeDragState.value.active && event.pointerId === nodeDragState.value.pointerId) {
    const pointer = getPointerCoordinates(event, nodeDragState.value.metrics);
    const deltaX = (pointer.x - nodeDragState.value.startX) / viewport.value.scale;
    const deltaY = (pointer.y - nodeDragState.value.startY) / viewport.value.scale;
    const moved = Math.abs(deltaX) > NODE_DRAG_THRESHOLD || Math.abs(deltaY) > NODE_DRAG_THRESHOLD;
    setNodeDragOffset(nodeDragState.value.nodeId, {
      x: nodeDragState.value.originOffsetX + deltaX,
      y: nodeDragState.value.originOffsetY + deltaY
    });
    if (moved) {
      nodeDragState.value.moved = true;
      hideTooltip();
    }
    return;
  }

  if (!panState.value.active || event.pointerId !== panState.value.pointerId) return;
  const pointer = getPointerCoordinates(event, panState.value.metrics);
  viewport.value.x = props.stretchTimeline
    ? 0
    : panState.value.originX + (pointer.x - panState.value.startX);
  viewport.value.y = panState.value.originY + (pointer.y - panState.value.startY);
}

function handleCanvasPointerUp(event) {
  if (nodeDragState.value.active && event.pointerId === nodeDragState.value.pointerId) {
    const nodeToOpen = nodeDragState.value.node;
    releasePointerCapture(nodeDragState.value.pointerId);
    if (nodeDragState.value.moved) {
      suppressNodeClick.value = {
        nodeId: nodeDragState.value.nodeId,
        expiresAt: Date.now() + 280
      };
    } else if (nodeToOpen) {
      openDetail(nodeToOpen);
    }
    clearNodeDragState();
    return;
  }

  if (panState.value.active && event.pointerId === panState.value.pointerId) {
    releasePointerCapture(panState.value.pointerId);
    clearPanState();
  }
}

function startNodeDrag(event, node) {
  if (event.pointerType === 'mouse' && event.button !== 0) return;
  const nodeId = String(node?.id || '').trim();
  if (!nodeId) return;
  const metrics = resolveCanvasMetrics();
  const pointer = getPointerCoordinates(event, metrics);
  const originOffset = getNodeDragOffset(nodeId);
  nodeDragState.value = {
    active: true,
    pointerId: event.pointerId,
    nodeId,
    node,
    startX: pointer.x,
    startY: pointer.y,
    originOffsetX: originOffset.x,
    originOffsetY: originOffset.y,
    moved: false,
    metrics
  };
  clearPanState();
  canvasRef.value?.setPointerCapture?.(event.pointerId);
}

function openDetail(node) {
  const nodeId = String(node?.id || '').trim();
  if (
    nodeId
    && nodeId === suppressNodeClick.value.nodeId
    && Number(suppressNodeClick.value.expiresAt || 0) >= Date.now()
  ) {
    return;
  }
  selectedNode.value = node;
}

function showTooltip(event, node) {
  if (!canvasRef.value) return;
  const canvasRect = canvasRef.value.getBoundingClientRect();
  let x = event.clientX - canvasRect.left + 12;
  let y = event.clientY - canvasRect.top - 12;
  if (x > canvasRef.value.clientWidth - 230) {
    x -= 220;
  }
  if (y > canvasRef.value.clientHeight - 80) {
    y -= 70;
  }
  tooltip.value = {
    visible: true,
    x,
    y,
    title: String(node?.title || '未命名论文'),
    meta: buildNodeTooltipMeta(node)
  };
}

function hideTooltip() {
  tooltip.value.visible = false;
}

async function resetLineageViewport({ targetScale = 1, forceRerender = false } = {}) {
  selectedNode.value = null;
  nodeOffsetMap.value = {};
  hideTooltip();
  clearPanState();
  clearNodeDragState();
  await nextTick();
  refreshViewportSize();
  viewport.value = buildCenteredViewport(targetScale);
  if (forceRerender) {
    renderNonce.value += 1;
  }
}

async function refreshLineageDisplay() {
  await resetLineageViewport({ targetScale: 1, forceRerender: true });
}

async function refreshLineageToMinOverview() {
  await resetLineageViewport({
    targetScale: viewportScaleRange.value.min,
    forceRerender: true
  });
}

function refreshViewportSize() {
  const viewportWidth = window.innerWidth || 1280;
  let minWidth = props.stretchTimeline ? 320 : 760;
  let minHeight = 420;
  if (viewportWidth <= 768) {
    minWidth = 260;
    minHeight = 300;
  } else if (viewportWidth <= 980) {
    minWidth = 300;
    minHeight = 340;
  }
  const width = Math.max(minWidth, Math.floor(canvasRef.value?.clientWidth || 920));
  const height = Math.max(minHeight, Math.floor(canvasRef.value?.clientHeight || 560));
  viewBox.value = { width, height };
  clampViewportScaleAroundCenter();
  if (props.stretchTimeline && viewport.value.x !== 0) {
    viewport.value.x = 0;
  }
}

function resolveFullscreenHost() {
  return canvasRef.value?.closest?.(FULLSCREEN_HOST_SELECTOR) || null;
}

function updateFullscreenState() {
  const layout = resolveFullscreenHost();
  if (!layout) {
    isFullscreen.value = false;
    return;
  }
  isFullscreen.value = layout.classList.contains('is-lineage-fullscreen');
}

async function toggleFullscreen() {
  const layout = resolveFullscreenHost();
  if (!layout) return;
  const nextState = !layout.classList.contains('is-lineage-fullscreen');
  layout.classList.toggle('is-lineage-fullscreen', nextState);
  isFullscreen.value = nextState;
  await nextTick();
  refreshViewportSize();
}

onMounted(async () => {
  await resetLineageViewport({ targetScale: viewport.value.scale });
  resizeObserver = new ResizeObserver(() => {
    refreshViewportSize();
  });
  if (canvasRef.value) {
    resizeObserver.observe(canvasRef.value);
  }
  updateFullscreenState();
});

watch(
  () => props.lineage,
  async () => {
    await resetLineageViewport({ targetScale: 1, forceRerender: true });
  },
  { deep: true }
);

onBeforeUnmount(() => {
  if (resizeObserver) {
    resizeObserver.disconnect();
  }
  const layout = resolveFullscreenHost();
  if (layout && layout.classList.contains('is-lineage-fullscreen')) {
    layout.classList.remove('is-lineage-fullscreen');
  }
  clearPanState();
  clearNodeDragState();
  isFullscreen.value = false;
});

defineExpose({
  refreshLineageDisplay,
  refreshLineageToMinOverview
});
</script>

<style scoped>
.blood-lineage {
  --blood-detail-width: clamp(280px, 30vw, 360px);
  --blood-head-height: 32px;
  --blood-head-offset: 12px;
  width: 100%;
  height: calc(100vh - 142px);
  min-height: 540px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--panel);
  overflow: hidden;
  display: grid;
  grid-template-rows: minmax(0, 1fr);
}

.blood-main {
  min-height: 0;
  display: flex;
}

.blood-canvas-wrap {
  flex: 1;
  position: relative;
  min-height: 0;
  background: var(--panel);
  cursor: grab;
  touch-action: none;
}

.blood-canvas-wrap.is-dragging {
  cursor: grabbing;
}

.blood-canvas-head {
  position: absolute;
  left: var(--blood-head-offset);
  right: var(--blood-head-offset);
  top: var(--blood-head-offset);
  height: var(--blood-head-height);
  z-index: 7;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  pointer-events: none;
}

.blood-canvas-head-right {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.blood-canvas-head-right {
  gap: 8px;
}

.blood-canvas-refresh,
.blood-canvas-fullscreen {
  flex-shrink: 0;
  pointer-events: auto;
}

.blood-tools-extra {
  min-width: 0;
  pointer-events: auto;
}

.blood-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.blood-time-axis {
  position: absolute;
  top: calc(var(--blood-head-offset) + var(--blood-head-height) + 6px);
  left: 0;
  right: 0;
  height: 30px;
  pointer-events: none;
  z-index: 5;
}

.blood-time-axis-track {
  position: absolute;
  inset: 0;
  transform-origin: 0 0;
}

.blood-year-line {
  position: absolute;
  top: 12px;
  bottom: 2px;
  width: 1px;
  background: var(--line);
}

.blood-year-label {
  position: absolute;
  top: 0;
  left: 0;
  transform: translateX(-50%);
  font-size: 10px;
  color: var(--muted);
}

.blood-legend {
  position: absolute;
  left: 12px;
  bottom: 12px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 10px;
  display: grid;
  gap: 6px;
  width: min(340px, calc(100% - 24px));
}

.blood-legend-title {
  font-size: 10px;
  color: var(--muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 0;
}

.blood-legend-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text);
}

.blood-legend-line {
  width: 20px;
  height: 2px;
  border-radius: 999px;
}

.blood-tooltip {
  position: absolute;
  min-width: 180px;
  max-width: 240px;
  border: 1px solid var(--line-2);
  border-radius: var(--radius-md);
  background: var(--bg);
  padding: 8px 10px;
  box-shadow: var(--shadow-soft);
  pointer-events: none;
}

.blood-tooltip-title {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text);
}

.blood-tooltip-meta {
  margin: 4px 0 0;
  font-size: 10px;
  color: var(--muted);
}

.blood-node-group {
  cursor: grab;
}

.blood-node-group.is-dragging {
  cursor: grabbing;
}

.blood-root-ring {
  fill: none;
  stroke: var(--line-2);
  stroke-dasharray: 3 2;
}

.blood-node-year {
  font-size: 9px;
}

.blood-node-cite {
  font-size: 8px;
}

.blood-node-label {
  font-size: 10px;
  fill: var(--text);
}

.blood-detail-panel {
  width: 0;
  border-left: 1px solid var(--line);
  background: var(--bg);
  overflow: hidden;
  transition: width 0.2s ease;
}

.blood-detail-panel.is-open {
  width: var(--blood-detail-width);
}

.blood-detail-head {
  height: 56px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}

.blood-detail-title {
  margin: 0;
  font-size: 13px;
  line-height: 1.4;
  color: var(--text);
}

.blood-detail-close {
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.blood-detail-body {
  padding: 12px;
  display: grid;
  gap: 12px;
}

.blood-detail-meta {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
}

.blood-detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.blood-detail-tag {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line-2);
  border-radius: 999px;
  background: var(--panel);
  color: var(--text);
  font-size: 11px;
  line-height: 1;
}

.blood-detail-grid {
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--panel);
  padding: 8px;
  display: grid;
  gap: 6px;
}

.blood-detail-grid-item {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}

.blood-detail-grid-label {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
}

.blood-detail-grid-value {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
  color: var(--text);
  word-break: break-word;
}

.blood-detail-section {
  display: grid;
  gap: 6px;
}

.blood-detail-section-title {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.blood-detail-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.65;
  color: var(--text);
  word-break: break-word;
}

.blood-detail-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  height: 30px;
  border: 1px solid var(--line-2);
  border-radius: var(--radius-sm);
  padding: 0 10px;
  color: var(--text);
  text-decoration: none;
  transition: background-color 0.2s ease;
}

.blood-detail-link:hover {
  background: var(--panel);
}

.blood-detail-id {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
  word-break: break-all;
}

.blood-detail-text.muted {
  color: var(--muted);
}

@media (max-width: 980px) {
  .blood-lineage {
    --blood-detail-width: clamp(236px, 68vw, 320px);
    height: clamp(520px, calc(100vh - 108px), 680px);
    min-height: 480px;
  }

  .blood-main {
    position: relative;
  }

  .blood-detail-panel {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 5;
    box-shadow: var(--shadow-soft);
  }

  .blood-detail-panel.is-open {
    width: var(--blood-detail-width);
  }

  .blood-legend {
    width: min(300px, calc(100% - 24px));
  }
}

@media (max-width: 768px) {
  .blood-lineage {
    --blood-detail-width: 100%;
    --blood-head-height: 30px;
    height: clamp(460px, calc(100vh - 82px), 580px);
    min-height: 400px;
  }

  .blood-detail-panel {
    border-left: 0;
    border-top: 1px solid var(--line);
  }

  .blood-detail-panel.is-open {
    width: var(--blood-detail-width);
  }
}
</style>
