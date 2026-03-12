<template>
  <section class="panel knowledge-graph-panel">
    <div class="knowledge-graph-body knowledge-graph-body-full">
      <div ref="graphContainerRef" class="knowledge-graph-canvas" role="img" aria-label="知识图谱可视化"></div>

      <div class="knowledge-toolbar-overlay">
        <label class="graph-toggle-row">
          <input v-model="simplifyDenseEdges" class="graph-toggle-input" type="checkbox" />
          <span class="mono">简化边（推荐）</span>
        </label>
        <label class="graph-toggle-row">
          <input v-model="showEdgeRelations" class="graph-toggle-input" type="checkbox" />
          <span class="mono">显示边关系标签</span>
        </label>
      </div>

      <div class="knowledge-legend-overlay">
        <p class="knowledge-legend-title mono">图例</p>
        <div class="legend-row">
          <span class="legend-dot node-paper"></span>论文（{{ counts.paper }}）
        </div>
        <div class="legend-row">
          <span class="legend-dot node-entity"></span>实体（{{ counts.entity }}）
        </div>
        <div class="legend-row">
          <span class="legend-dot node-domain"></span>领域（{{ counts.domain }}）
        </div>
        <div class="legend-row">
          <span class="legend-line edge-generic"></span>关系边（{{ counts.visible_edges }} / {{ counts.total_edges }}）
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { Graph } from '@antv/g6';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = defineProps({
  graphData: {
    type: Object,
    required: true
  }
});

const graphContainerRef = ref(null);
const simplifyDenseEdges = ref(true);
const showEdgeRelations = ref(false);
let graphInstance = null;
let resizeObserver = null;
let resizeRaf = 0;

const ENTITY_PALETTE = [
  { fill: '#fbe7d4', stroke: '#cc8d54' },
  { fill: '#e6f4d8', stroke: '#7ea257' },
  { fill: '#dff0fb', stroke: '#4f89bb' },
  { fill: '#fbe3ee', stroke: '#bb6f94' },
  { fill: '#efe8fb', stroke: '#7d69be' },
  { fill: '#e2f6ef', stroke: '#4f9e82' },
  { fill: '#f8efd8', stroke: '#b59a4c' },
  { fill: '#f3e7df', stroke: '#b07b68' }
];

const NODE_TYPE_COLORS = {
  paper: { fill: '#f4f5f7', stroke: '#8b94a2' },
  domain: { fill: '#e8eefc', stroke: '#5d7ec8' }
};

const EDGE_STROKE = '#d2d6dd';
const EDGE_LABEL = {
  mentions: 'mentions',
  belongs_to: 'belongs_to',
  related: 'related',
  covers: 'covers'
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function shortLabel(text) {
  const value = String(text || '');
  return value.length > 20 ? `${value.slice(0, 18)}...` : value;
}

function hashText(value) {
  const input = String(value || '');
  let hash = 0;
  for (let i = 0; i < input.length; i += 1) {
    hash = (hash << 5) - hash + input.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function getNodeColor(node) {
  if (node.type === 'entity') {
    const paletteIndex = hashText(node.label || node.id) % ENTITY_PALETTE.length;
    return ENTITY_PALETTE[paletteIndex];
  }
  return NODE_TYPE_COLORS[node.type] || NODE_TYPE_COLORS.paper;
}

function toWeightedEdges(rawEdges) {
  return (rawEdges || []).map((edge, index) => ({
    ...edge,
    __index: index,
    __weight: Number(edge.weight || 0)
  }));
}

function pickTop(edges, limit) {
  if (!edges.length || limit <= 0) return [];
  return edges
    .slice()
    .sort((left, right) => right.__weight - left.__weight)
    .slice(0, limit);
}

function collectRenderableEdges(rawEdges, totalNodes, simplifyEnabled) {
  const prepared = toWeightedEdges(rawEdges);
  if (!simplifyEnabled || prepared.length <= 60) return prepared;

  const hardCap = clamp(Math.round(totalNodes * 1.45), 46, 110);
  const byRelation = {
    mentions: [],
    belongs_to: [],
    related: [],
    covers: [],
    other: []
  };

  for (const edge of prepared) {
    const relation = String(edge.relation || '');
    if (relation in byRelation) {
      byRelation[relation].push(edge);
    } else {
      byRelation.other.push(edge);
    }
  }

  const relationLimits = {
    mentions: clamp(Math.round(totalNodes * 0.7), 14, 46),
    belongs_to: clamp(Math.round(totalNodes * 0.4), 6, 20),
    related: clamp(Math.round(totalNodes * 0.34), 5, 18),
    covers: clamp(Math.round(totalNodes * 0.3), 4, 16),
    other: clamp(Math.round(totalNodes * 0.15), 3, 10)
  };

  const seeded = [
    ...pickTop(byRelation.mentions, relationLimits.mentions),
    ...pickTop(byRelation.belongs_to, relationLimits.belongs_to),
    ...pickTop(byRelation.related, relationLimits.related),
    ...pickTop(byRelation.covers, relationLimits.covers),
    ...pickTop(byRelation.other, relationLimits.other)
  ];

  const selected = new Map();
  for (const edge of seeded) {
    selected.set(edge.__index, edge);
  }

  if (selected.size < hardCap) {
    const remaining = prepared
      .filter((edge) => !selected.has(edge.__index))
      .sort((left, right) => right.__weight - left.__weight);

    for (const edge of remaining) {
      selected.set(edge.__index, edge);
      if (selected.size >= hardCap) break;
    }
  }

  return [...selected.values()];
}

function buildDegreeMap(edges) {
  const degree = new Map();
  for (const edge of edges) {
    const source = String(edge.source || '');
    const target = String(edge.target || '');
    if (source) degree.set(source, (degree.get(source) || 0) + 1);
    if (target) degree.set(target, (degree.get(target) || 0) + 1);
  }
  return degree;
}

function nodeSize(rawSize, nodeType, totalNodes, degree) {
  const cleanSize = Number(rawSize || 1);
  const densityFactor = clamp(22 / Math.max(10, totalNodes), 0.46, 1.2);
  const degreeBoost = Math.sqrt(Math.max(1, degree));
  const rawBoost = Math.sqrt(Math.max(1, cleanSize));
  const typeBase = nodeType === 'domain' ? 9.5 : nodeType === 'paper' ? 8.6 : 7.8;
  const upper = totalNodes > 56 ? 18 : totalNodes > 36 ? 22 : 26;
  const scaled = (typeBase + degreeBoost * 2.05 + rawBoost * 0.65) * densityFactor;
  return clamp(scaled, 6.5, upper);
}

function edgeWidth(weight) {
  return clamp(0.55 + Number(weight || 0) * 0.95, 0.55, 1.55);
}

function getContainerSize() {
  const container = graphContainerRef.value;
  const width = Math.max(420, Math.floor(container?.clientWidth || 920));
  const height = Math.max(420, Math.floor(container?.clientHeight || 560));
  return { width, height };
}

function toG6Data(raw, options = {}) {
  const nodesRaw = raw?.nodes || [];
  const edgesRaw = raw?.edges || [];
  const totalNodes = Math.max(1, nodesRaw.length);
  const visibleEdges = collectRenderableEdges(edgesRaw, totalNodes, options.simplifyEdges);
  const degreeMap = buildDegreeMap(visibleEdges);
  const labelThreshold = totalNodes > 60 ? 4 : totalNodes > 34 ? 3 : 1;
  const edgeLabelEnabled = options.showEdgeLabels && visibleEdges.length <= 120;

  const nodes = nodesRaw.map((node) => {
    const color = getNodeColor(node);
    const degree = degreeMap.get(node.id) || 0;
    const size = nodeSize(node.size, node.type, totalNodes, degree);
    const showLabel = totalNodes <= 24 || node.type === 'domain' || degree >= labelThreshold;

    return {
      id: node.id,
      data: {
        ...node,
        nodeType: node.type,
        rawSize: Number(node.size || 1),
        resolvedSize: size,
        degree
      },
      style: {
        size,
        fill: color.fill,
        stroke: color.stroke,
        lineWidth: node.type === 'entity' ? 1.0 : 1.2,
        shadowBlur: 5,
        shadowColor: 'rgba(20, 28, 40, 0.04)',
        label: showLabel,
        labelText: shortLabel(node.label),
        labelPlacement: 'bottom',
        labelOffsetY: 6,
        labelFontSize: totalNodes > 44 ? 9 : 10,
        labelFill: '#3a3f46',
        labelBackground: false,
        cursor: 'pointer'
      }
    };
  });

  const edges = visibleEdges.map((edge) => ({
    id: `${edge.source}-${edge.target}-${edge.__index}`,
    source: edge.source,
    target: edge.target,
    data: {
      ...edge,
      relation: edge.relation,
      rawWeight: Number(edge.weight || 0)
    },
    style: {
      stroke: EDGE_STROKE,
      lineWidth: edgeWidth(edge.weight),
      strokeOpacity: 0.62,
      endArrow: true,
      endArrowSize: 6,
      lineDash: edge.relation === 'covers' ? [4, 3] : undefined,
      label: edgeLabelEnabled,
      labelText: EDGE_LABEL[edge.relation] || String(edge.relation || ''),
      labelPlacement: 'center',
      labelFill: '#8a929f',
      labelFontSize: 9,
      labelBackground: true,
      labelBackgroundFill: 'rgba(255,255,255,0.9)',
      labelBackgroundRadius: 3,
      labelBackgroundPadding: [2, 4],
      cursor: 'pointer'
    }
  }));

  return { nodes, edges };
}

function buildLayout(width, height, totalNodes, visibleEdgeCount) {
  const crowdFactor = clamp(visibleEdgeCount / Math.max(1, totalNodes), 1.3, 6.8);

  return {
    type: 'd3-force',
    animation: true,
    preventOverlap: true,
    center: [width / 2, height / 2],
    alphaDecay: 0.08,
    velocityDecay: 0.5,
    iterations: 220,
    manyBody: {
      strength: -560 - crowdFactor * 130,
      distanceMax: 1200
    },
    link: {
      distance: (edge) => {
        const relation = edge?.data?.relation;
        if (relation === 'related') return 240;
        if (relation === 'belongs_to') return 218;
        return 198;
      },
      strength: 0.62
    },
    collide: {
      strength: 0.9,
      iterations: 5,
      radius: (node) => Number(node?.data?.resolvedSize || 10) / 2 + 18
    }
  };
}

function graphOptions(width, height) {
  const totalNodes = Math.max(1, props.graphData?.nodes?.length || 0);
  const visibleEdges = collectRenderableEdges(
    props.graphData?.edges || [],
    totalNodes,
    simplifyDenseEdges.value
  );

  return {
    width,
    height,
    autoFit: 'view',
    padding: 20,
    data: toG6Data(props.graphData, {
      showEdgeLabels: showEdgeRelations.value,
      simplifyEdges: simplifyDenseEdges.value
    }),
    layout: buildLayout(width, height, totalNodes, visibleEdges.length),
    node: {
      type: 'circle'
    },
    edge: {
      type: 'quadratic'
    },
    behaviors: [
      { type: 'drag-element-force' },
      { type: 'zoom-canvas' },
      { type: 'drag-canvas' },
      { type: 'hover-activate' }
    ]
  };
}

async function initGraph() {
  if (!graphContainerRef.value || graphInstance) return;
  const { width, height } = getContainerSize();

  graphInstance = new Graph({
    container: graphContainerRef.value,
    ...graphOptions(width, height)
  });

  await graphInstance.render();
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

const counts = computed(() => {
  const result = {
    paper: 0,
    entity: 0,
    domain: 0,
    total_edges: 0,
    visible_edges: 0
  };

  const nodes = props.graphData.nodes || [];
  const edges = props.graphData.edges || [];
  const totalNodes = Math.max(1, nodes.length);

  for (const node of nodes) {
    if (node.type in result) result[node.type] += 1;
  }

  result.total_edges = edges.length;
  result.visible_edges = collectRenderableEdges(edges, totalNodes, simplifyDenseEdges.value).length;
  return result;
});

watch(
  () => props.graphData,
  async () => {
    await updateGraphData();
  },
  { deep: true }
);

watch([showEdgeRelations, simplifyDenseEdges], async () => {
  await updateGraphData();
});

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
    graphInstance.destroy();
    graphInstance = null;
  }
});
</script>
