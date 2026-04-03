import { buildDomainEdgeTopology } from './knowledgeDomainTopology';

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizeRate(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return clamp(parsed, 0, 1);
}

function hashText(value) {
  const input = String(value || '');
  let hash = 0;
  for (let index = 0; index < input.length; index += 1) {
    hash = (hash << 5) - hash + input.charCodeAt(index);
    hash |= 0;
  }
  return Math.abs(hash);
}

function resolveNodeKind(node) {
  return String(node?.kind || node?.type || '').trim().toLowerCase();
}

function parseDomainOrder(domainId) {
  const matched = String(domainId || '').match(/^domain:(\d+):/);
  if (!matched) return Number.POSITIVE_INFINITY;
  const parsed = Number(matched[1]);
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

function resolveNodeTier(node) {
  const parsed = Number(node?.tier ?? node?.meta?.tier);
  if (!Number.isFinite(parsed)) return 3;
  const safeTier = Math.round(parsed);
  if (safeTier < 1 || safeTier > 3) return 3;
  return safeTier;
}

function createSeededRandom(seedInput) {
  let seed = (hashText(seedInput) >>> 0) || 0x9e3779b9;
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

function buildRandomDomainAnchors(domainIds, width, height) {
  const safeDomains = Array.from(domainIds || [])
    .sort((left, right) => {
      const orderDiff = parseDomainOrder(left) - parseDomainOrder(right);
      if (Number.isFinite(orderDiff) && Math.abs(orderDiff) > 1e-6) return orderDiff;
      return String(left).localeCompare(String(right));
    });
  if (!safeDomains.length) return new Map();

  const centerX = width / 2;
  const centerY = height / 2;
  const spreadX = clamp(width * 0.32, 150, 420);
  const spreadY = clamp(height * 0.26, 120, 320);
  const rng = createSeededRandom(`${safeDomains.join('|')}|${width}x${height}`);

  const slotPoints = [];
  while (slotPoints.length < safeDomains.length) {
    const baseDx = (0.16 + rng() * 0.34) * spreadX;
    const baseDy = (rng() * 2 - 1) * spreadY * 0.9;
    slotPoints.push({
      x: centerX - baseDx,
      y: centerY + baseDy
    });
    if (slotPoints.length >= safeDomains.length) break;
    slotPoints.push({
      x: centerX + baseDx + (rng() * 2 - 1) * 20,
      y: centerY - baseDy * 0.74 + (rng() * 2 - 1) * 20
    });
  }

  const anchors = new Map();
  safeDomains.forEach((domainId, index) => {
    const slot = slotPoints[index] || { x: centerX, y: centerY };
    anchors.set(domainId, {
      x: clamp(slot.x, width * 0.14, width * 0.86),
      y: clamp(slot.y, height * 0.14, height * 0.86)
    });
  });
  return anchors;
}

function resolveEntityDomainById(topology) {
  const domainByEntityId = new Map();
  for (const [domainId, entityIds] of (topology?.domainEntityIdsById || new Map()).entries()) {
    for (const entityId of entityIds || []) {
      if (!domainByEntityId.has(entityId)) {
        domainByEntityId.set(entityId, domainId);
      }
    }
  }
  return domainByEntityId;
}

function buildStandaloneRingTargets(nodesRaw, width, height) {
  const centerX = width / 2;
  const centerY = height / 2;
  const targets = new Map();
  const paperIds = new Set();
  const entityIds = new Set();
  const otherIds = new Set();

  for (const node of nodesRaw || []) {
    const nodeId = String(node?.id || '').trim();
    if (!nodeId) continue;
    const kind = resolveNodeKind(node);
    if (kind === 'seed' || kind === 'domain') continue;
    if (kind === 'paper') {
      paperIds.add(nodeId);
      continue;
    }
    if (kind === 'entity') {
      entityIds.add(nodeId);
      continue;
    }
    otherIds.add(nodeId);
  }

  const sortedOuterIds = [...paperIds, ...otherIds]
    .filter(Boolean)
    .sort((left, right) => String(left).localeCompare(String(right)));
  const sortedInnerIds = [...entityIds]
    .filter(Boolean)
    .sort((left, right) => String(left).localeCompare(String(right)));

  const outerRadius = clamp(Math.min(width, height) * 0.36, 148, 430);
  const innerRadius = clamp(Math.min(width, height) * 0.24, 96, 300);
  const baseAngle = -Math.PI / 2;

  const placeOnRing = (ids, radius, strength, angleOffset = 0) => {
    if (!ids.length) return;
    const step = (Math.PI * 2) / ids.length;
    ids.forEach((nodeId, index) => {
      const angle = baseAngle + angleOffset + step * index;
      targets.set(nodeId, {
        x: clamp(centerX + Math.cos(angle) * radius, width * 0.08, width * 0.92),
        y: clamp(centerY + Math.sin(angle) * radius, height * 0.1, height * 0.9),
        strength
      });
    });
  };

  placeOnRing(sortedOuterIds, outerRadius, 0.14, 0);
  placeOnRing(
    sortedInnerIds,
    innerRadius,
    0.12,
    sortedInnerIds.length > 1 ? Math.PI / sortedInnerIds.length : 0
  );

  return targets;
}

function buildNodeTargetMap(nodesRaw, topology, width, height) {
  const centerX = width / 2;
  const centerY = height / 2;
  const domainIds = new Set(
    (nodesRaw || [])
      .filter((node) => resolveNodeKind(node) === 'domain')
      .map((node) => String(node?.id || '').trim())
      .filter(Boolean)
  );
  const domainAnchors = buildRandomDomainAnchors(domainIds, width, height);
  const entityDomainById = resolveEntityDomainById(topology);
  const targetByNodeId = new Map();
  const standaloneTargets = domainAnchors.size
    ? new Map()
    : buildStandaloneRingTargets(nodesRaw, width, height);
  const jitterRandomByDomain = new Map();
  const resolveDomainRandom = (domainId) => {
    const safeDomainId = String(domainId || '').trim();
    if (!safeDomainId) return createSeededRandom('global');
    if (jitterRandomByDomain.has(safeDomainId)) {
      return jitterRandomByDomain.get(safeDomainId);
    }
    const random = createSeededRandom(`${safeDomainId}|cluster`);
    jitterRandomByDomain.set(safeDomainId, random);
    return random;
  };

  for (const node of nodesRaw || []) {
    const nodeId = String(node?.id || '').trim();
    if (!nodeId) continue;
    const kind = resolveNodeKind(node);

    if (kind === 'seed') {
      targetByNodeId.set(nodeId, { x: centerX, y: centerY, strength: 0.28 });
      continue;
    }
    if (kind === 'domain') {
      const anchor = domainAnchors.get(nodeId) || { x: centerX, y: centerY };
      targetByNodeId.set(nodeId, { x: anchor.x, y: anchor.y, strength: 0.42 });
      continue;
    }

    if (!domainAnchors.size && standaloneTargets.has(nodeId)) {
      targetByNodeId.set(nodeId, standaloneTargets.get(nodeId));
      continue;
    }

    let domainId = '';
    if (kind === 'paper') {
      domainId = String(topology?.paperDomainById?.get(nodeId) || '').trim();
    } else if (kind === 'entity') {
      domainId = String(entityDomainById.get(nodeId) || '').trim();
    }

    if (domainId && domainAnchors.has(domainId)) {
      const anchor = domainAnchors.get(domainId);
      const tier = resolveNodeTier(node);
      const random = resolveDomainRandom(domainId);
      const innerBase = kind === 'paper'
        ? (tier <= 1 ? 72 : (tier === 2 ? 94 : 118))
        : 136;
      const radius = Math.max(50, innerBase * (0.68 + random() * 0.62));
      const angle = random() * Math.PI * 2;
      targetByNodeId.set(nodeId, {
        x: clamp(anchor.x + Math.cos(angle) * radius, width * 0.08, width * 0.92),
        y: clamp(anchor.y + Math.sin(angle) * radius, height * 0.1, height * 0.9),
        strength: kind === 'paper' ? 0.2 : 0.16
      });
      continue;
    }

    const random = createSeededRandom(nodeId);
    const outerRadiusX = clamp(Math.min(width, height) * 0.38, 170, 420);
    const outerRadiusY = clamp(Math.min(width, height) * 0.32, 140, 360);
    const angle = random() * Math.PI * 2;
    const radial = 0.42 + random() * 0.58;
    targetByNodeId.set(nodeId, {
      x: clamp(centerX + Math.cos(angle) * outerRadiusX * radial, width * 0.08, width * 0.92),
      y: clamp(centerY + Math.sin(angle) * outerRadiusY * radial, height * 0.1, height * 0.9),
      strength: 0.1
    });
  }

  return targetByNodeId;
}

function edgeDistance(relevance, kind) {
  const normalized = normalizeRate(relevance);
  if (kind === 'center') {
    return clamp(360 - normalized * 210, 135, 360);
  }
  return clamp(430 - normalized * 150, 250, 430);
}

function edgeStrength(edge) {
  const normalized = normalizeRate(edge?.data?.relevance);
  if (edge?.data?.kind === 'center') {
    return clamp(0.52 + normalized * 0.34, 0.52, 0.9);
  }
  return clamp(0.18 + normalized * 0.28, 0.18, 0.5);
}

function resolveNodeTarget(targetByNodeId, node, fallbackX, fallbackY) {
  const nodeId = String(node?.id || node?.data?.id || '').trim();
  const target = targetByNodeId.get(nodeId);
  if (target) return target;
  return { x: fallbackX, y: fallbackY, strength: 0.08 };
}

export function buildBalancedForceLayout({
  nodesRaw,
  edgesRaw,
  width,
  height,
  totalNodes,
  edgeCount
}) {
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

  const topology = buildDomainEdgeTopology(nodesRaw || [], edgesRaw || []);
  const targetByNodeId = buildNodeTargetMap(nodesRaw || [], topology, width, height);
  const centerX = width / 2;
  const centerY = height / 2;
  const crowdFactor = clamp(edgeCount / Math.max(1, totalNodes), 1.2, 6.4);

  return {
    type: 'd3-force',
    animation: true,
    preventOverlap: true,
    center: [centerX, centerY],
    alphaDecay: 0.064,
    velocityDecay: 0.4,
    iterations: 320,
    manyBody: {
      strength: -700 - crowdFactor * 64,
      distanceMax: 1320
    },
    link: {
      distance: (edge) => edgeDistance(edge?.data?.relevance, edge?.data?.kind),
      strength: (edge) => edgeStrength(edge)
    },
    x: {
      strength: (node) => resolveNodeTarget(targetByNodeId, node, centerX, centerY).strength,
      x: (node) => resolveNodeTarget(targetByNodeId, node, centerX, centerY).x
    },
    y: {
      strength: (node) => resolveNodeTarget(targetByNodeId, node, centerX, centerY).strength,
      y: (node) => resolveNodeTarget(targetByNodeId, node, centerX, centerY).y
    },
    collide: {
      strength: 0.92,
      iterations: 7,
      radius: (node) => Number(node?.data?.resolvedSize || 11) / 2 + 19
    }
  };
}
