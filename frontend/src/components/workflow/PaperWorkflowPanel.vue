<template>
  <aside class="paper-workflow-panel panel">
    <div class="paper-workflow-progress-row">
      <p class="paper-workflow-progress-title">研究进度</p>
      <div class="paper-workflow-progress-track">
        <div class="paper-workflow-progress-fill" :style="{ width: `${safeProgress}%` }"></div>
      </div>
      <p class="paper-workflow-progress-text mono">{{ safeProgress }}%</p>
      <button
        v-if="canTerminate"
        class="paper-workflow-progress-stop-btn"
        type="button"
        :disabled="Boolean(terminating)"
        aria-label="终止工作流"
        title="终止工作流"
        @click="$emit('terminate')"
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="10" cy="10" r="7.1" fill="none" stroke="currentColor" stroke-width="1.4"></circle>
          <circle cx="10" cy="10" r="3.4" fill="currentColor"></circle>
        </svg>
      </button>
    </div>

    <div class="paper-workflow-step-list">
      <article
        v-for="(step, index) in steps"
        :key="step.key || index"
        class="paper-workflow-step-item"
        :class="`is-${stepStatus(step.status)}`"
      >
        <div class="paper-workflow-step-indicator mono">
          <span v-if="stepStatus(step.status) === 'done'">✓</span>
          <span v-else-if="stepStatus(step.status) === 'active'">●</span>
          <span v-else-if="stepStatus(step.status) === 'paused'">⏸</span>
          <span v-else-if="stepStatus(step.status) === 'failed'">!</span>
          <span v-else>○</span>
        </div>
        <div class="paper-workflow-step-main">
          <div class="paper-workflow-step-head">
            <p class="paper-workflow-step-label">{{ step.title || `步骤 ${index + 1}` }}</p>
            <button
              class="paper-workflow-step-toggle-btn"
              :class="{ 'is-collapsed': isStepCollapsed(step, index) }"
              type="button"
              :aria-label="isStepCollapsed(step, index) ? '展开步骤' : '折叠步骤'"
              :title="isStepCollapsed(step, index) ? '展开步骤' : '折叠步骤'"
              @click="toggleStepCollapsed(step, index)"
            >
              <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                <path
                  v-if="isStepCollapsed(step, index)"
                  d="M2.5 4.2 6 7.8l3.5-3.6"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.4"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                <path
                  v-else
                  d="M2.5 7.8 6 4.2l3.5 3.6"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.4"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>

          <template v-if="!isStepCollapsed(step, index)">
            <section
              v-if="hasNegotiationState(step?.key)"
              class="paper-workflow-negotiation"
            >
              <div class="paper-workflow-negotiation-head">
                <p class="paper-workflow-negotiation-round mono">
                  协商轮次 R{{ resolveNegotiationRound(step?.key) }}
                </p>
                <span
                  class="paper-workflow-negotiation-status mono"
                  :class="`is-${resolveNegotiationStatus(step?.key)}`"
                >
                  {{ resolveNegotiationStatusText(step?.key) }}
                </span>
              </div>

              <p class="paper-workflow-negotiation-task">{{ resolveNegotiationTaskLabel(step?.key) }}</p>

              <div class="paper-workflow-negotiation-flow mono">
                <span>Coordinator</span>
                <span class="paper-workflow-negotiation-arrow">→</span>
                <span>候选 Agent</span>
              </div>

              <div class="paper-workflow-negotiation-bids">
                <article
                  v-for="(bid, bidIndex) in resolveNegotiationBids(step?.key)"
                  :key="`${step?.key || 'unknown'}-bid-${bidIndex}-${String(bid?.agentId || '')}`"
                  class="paper-workflow-negotiation-bid"
                  :class="`is-${resolveBidStatus(bid?.status)}`"
                >
                  <div class="paper-workflow-negotiation-bid-head">
                    <p class="paper-workflow-negotiation-bid-title mono">
                      {{ String(bidIndex + 1).padStart(2, '0') }} {{ resolveBidLabel(bid) }}
                    </p>
                    <span class="paper-workflow-negotiation-bid-badge mono" :class="`is-${resolveBidStatus(bid?.status)}`">
                      {{ resolveBidStatusText(bid?.status) }}
                    </span>
                  </div>
                  <p class="paper-workflow-negotiation-bid-metrics mono">
                    置信度 {{ formatBidConfidenceMetric(bid?.confidence) }} · 耗时 {{ formatBidLatencyMetric(bid?.estimatedLatencyMs) }} · 成本 {{ formatBidCostMetric(bid?.estimatedCost) }}
                  </p>
                </article>
              </div>

              <div v-if="hasNegotiationResult(step?.key)" class="paper-workflow-negotiation-result">
                <p v-if="resolveNegotiationWinner(step?.key)" class="paper-workflow-negotiation-result-item is-winner">
                  中标：{{ resolveBidLabel(resolveNegotiationWinner(step?.key)) }}
                </p>
                <p v-if="resolveNegotiationVeto(step?.key)" class="paper-workflow-negotiation-result-item is-veto">
                  否决：{{ resolveNegotiationVeto(step?.key)?.reason || '执行结果未通过质量审核。' }}
                </p>
                <p v-if="resolveNegotiationRebid(step?.key)" class="paper-workflow-negotiation-result-item is-rebid">
                  重投标：{{ resolveNegotiationRebidText(step?.key) }}
                </p>
              </div>

              <div v-if="hasNegotiationBudget(step?.key)" class="paper-workflow-negotiation-budget">
                <div class="paper-workflow-negotiation-budget-track">
                  <div
                    class="paper-workflow-negotiation-budget-fill"
                    :style="{ width: `${resolveNegotiationBudgetPercent(step?.key)}%` }"
                  ></div>
                </div>
                <p class="paper-workflow-negotiation-budget-text mono">{{ resolveNegotiationBudgetText(step?.key) }}</p>
              </div>
            </section>

            <div v-if="step.logs && step.logs.length" class="paper-workflow-trace-list">
              <article
                v-for="(log, logIndex) in step.logs"
                :key="`${step.key || index}-log-${logIndex}`"
                class="paper-workflow-trace-item"
              >
                <div class="paper-workflow-trace-head">
                  <p class="paper-workflow-trace-title mono">{{ String(logIndex + 1).padStart(2, '0') }} {{ log.title }}</p>
                  <span class="paper-workflow-trace-badge mono" :class="`is-${traceStatus(log.status)}`">
                    {{ traceStatusText(log.status) }}
                  </span>
                </div>
                <p class="paper-workflow-trace-detail">{{ log.detail }}</p>
              </article>
            </div>

            <button
              v-if="isActionRequired(step)"
              class="btn btn-accent mono paper-workflow-action-btn"
              type="button"
              :disabled="Boolean(step?.action?.disabled)"
              @click="$emit('step-action', step.key)"
            >
              {{ String(step?.action?.label || '继续执行') }}
            </button>
          </template>
        </div>
      </article>
    </div>

  </aside>
</template>

<script setup>
import { computed, ref } from 'vue';

const NEGOTIATION_TASK_LABEL = {
  planner: '任务规划协商',
  router: '任务路由协商',
  search: '论文检索协商',
  checkpoint_1: '需求确认协商',
  graph_build: '图谱构建协商',
  checkpoint_2: '血缘确认协商',
  parallel: '血缘分析协商'
};

const props = defineProps({
  steps: {
    type: Array,
    default: () => []
  },
  progress: {
    type: Number,
    default: 0
  },
  negotiationByStep: {
    type: Object,
    default: () => ({})
  },
  canTerminate: {
    type: Boolean,
    default: false
  },
  terminating: {
    type: Boolean,
    default: false
  }
});

defineEmits(['step-action', 'terminate']);

const safeProgress = computed(() => {
  const value = Number(props.progress);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
});

const collapsedStepState = ref(Object.create(null));

function resolveStepCollapseKey(step, index) {
  const stepKey = String(step?.key || '').trim();
  if (stepKey) return stepKey;
  return `step-${Number(index) || 0}`;
}

function isStepCollapsed(step, index) {
  const stepKey = resolveStepCollapseKey(step, index);
  return Boolean(collapsedStepState.value?.[stepKey]);
}

function toggleStepCollapsed(step, index) {
  const stepKey = resolveStepCollapseKey(step, index);
  collapsedStepState.value = {
    ...collapsedStepState.value,
    [stepKey]: !collapsedStepState.value?.[stepKey]
  };
}

function normalizeStatus(rawStatus) {
  const status = String(rawStatus || '').trim().toLowerCase();
  if (status === 'running' || status === 'doing') return 'active';
  if (status === 'done' || status === 'completed' || status === 'skipped') return 'done';
  if (status === 'failed' || status === 'fallback' || status === 'error') return 'failed';
  if (status === 'action_required') return 'paused';
  return 'pending';
}

function stepStatus(rawStatus) {
  return normalizeStatus(rawStatus);
}

function traceStatus(rawStatus) {
  return normalizeStatus(rawStatus);
}

function traceStatusText(rawStatus) {
  const normalized = normalizeStatus(rawStatus);
  if (normalized === 'active') return '进行中';
  if (normalized === 'done') return '已完成';
  if (normalized === 'failed') return '失败';
  if (normalized === 'paused') return '待确认';
  return '准备中';
}

function normalizeNegotiationStatus(rawStatus) {
  const status = String(rawStatus || '').trim().toLowerCase();
  if (status === 'awarded') return 'awarded';
  if (status === 'vetoed') return 'vetoed';
  if (status === 'rebid') return 'rebid';
  return 'bidding';
}

function resolveStepNegotiation(stepKey) {
  const safeStepKey = String(stepKey || '').trim();
  if (!safeStepKey) return null;
  const payload = props.negotiationByStep?.[safeStepKey];
  if (!payload || typeof payload !== 'object') return null;
  if (!Array.isArray(payload.rounds) || !payload.rounds.length) return null;
  return payload;
}

function resolveStepRound(stepKey) {
  const payload = resolveStepNegotiation(stepKey);
  if (!payload) return null;
  const activeRound = Number(payload?.activeRound || 0);
  if (Number.isFinite(activeRound) && activeRound > 0) {
    const found = payload.rounds.find((item) => Number(item?.round || 0) === Math.round(activeRound));
    if (found) return found;
  }
  return payload.rounds[payload.rounds.length - 1] || null;
}

function hasNegotiationState(stepKey) {
  return Boolean(resolveStepRound(stepKey));
}

function resolveNegotiationRound(stepKey) {
  const roundState = resolveStepRound(stepKey);
  return Number.isFinite(Number(roundState?.round)) ? Math.max(1, Math.round(Number(roundState.round))) : 1;
}

function resolveNegotiationTaskLabel(stepKey) {
  const payload = resolveStepNegotiation(stepKey);
  const roundState = resolveStepRound(stepKey);
  const taskKind = String(roundState?.taskKind || payload?.activeTaskKind || '').trim().toLowerCase();
  if (!taskKind) return '执行任务协商';
  return NEGOTIATION_TASK_LABEL[taskKind] || `${taskKind} 协商`;
}

function resolveNegotiationStatus(stepKey) {
  const roundState = resolveStepRound(stepKey);
  return normalizeNegotiationStatus(roundState?.status);
}

function resolveNegotiationStatusText(stepKey) {
  const status = resolveNegotiationStatus(stepKey);
  if (status === 'awarded') return '已授约';
  if (status === 'vetoed') return '已否决';
  if (status === 'rebid') return '重投标';
  return '竞标中';
}

function resolveNegotiationBids(stepKey) {
  const roundState = resolveStepRound(stepKey);
  return Array.isArray(roundState?.bids) ? roundState.bids : [];
}

function resolveBidStatus(rawStatus) {
  const status = String(rawStatus || '').trim().toLowerCase();
  if (status === 'winner') return 'winner';
  if (status === 'vetoed') return 'vetoed';
  return 'bid';
}

function resolveBidStatusText(rawStatus) {
  const status = resolveBidStatus(rawStatus);
  if (status === 'winner') return '中标';
  if (status === 'vetoed') return '否决';
  return '竞标';
}

function resolveBidLabel(bid) {
  const label = String(bid?.label || '').trim();
  if (label) return label;
  const agentId = String(bid?.agentId || '').trim();
  return agentId || 'Agent';
}

function parseMetricValue(rawValue) {
  if (rawValue === null || rawValue === undefined) return null;
  if (typeof rawValue === 'string' && !rawValue.trim()) return null;
  const value = Number(rawValue);
  return Number.isFinite(value) ? value : null;
}

function formatBidConfidence(rawValue) {
  const value = Number(rawValue);
  return Number.isFinite(value) ? value.toFixed(3) : '-';
}

function formatBidLatency(rawValue) {
  const value = Number(rawValue);
  return Number.isFinite(value) ? `${Math.max(1, Math.round(value))}ms` : '-';
}

function formatBidCost(rawValue) {
  const value = Number(rawValue);
  return Number.isFinite(value) ? value.toFixed(3) : '-';
}

function formatBidConfidenceMetric(rawValue) {
  const value = parseMetricValue(rawValue);
  if (!Number.isFinite(value) || value <= 0) return '计算中';
  return value.toFixed(3);
}

function formatBidLatencyMetric(rawValue) {
  const value = parseMetricValue(rawValue);
  if (!Number.isFinite(value) || value <= 0) return '计算中';
  return `${Math.max(1, Math.round(value))}ms`;
}

function formatBidCostMetric(rawValue) {
  const value = parseMetricValue(rawValue);
  if (!Number.isFinite(value) || value <= 0) return '计算中';
  return value.toFixed(3);
}

function resolveNegotiationWinner(stepKey) {
  const roundState = resolveStepRound(stepKey);
  if (roundState?.winner && typeof roundState.winner === 'object') {
    return roundState.winner;
  }
  const bids = resolveNegotiationBids(stepKey);
  return bids.find((item) => resolveBidStatus(item?.status) === 'winner') || null;
}

function resolveNegotiationVeto(stepKey) {
  const roundState = resolveStepRound(stepKey);
  if (!roundState?.veto || typeof roundState.veto !== 'object') return null;
  return roundState.veto;
}

function resolveNegotiationRebid(stepKey) {
  const roundState = resolveStepRound(stepKey);
  if (!roundState?.rebid || typeof roundState.rebid !== 'object') return null;
  return roundState.rebid;
}

function resolveNegotiationRebidText(stepKey) {
  const rebid = resolveNegotiationRebid(stepKey);
  if (!rebid) return '正在重新发起竞标。';
  const reason = String(rebid.reason || '').trim() || '正在重新发起竞标。';
  const retryCount = Number(rebid.retryCount);
  if (!Number.isFinite(retryCount) || retryCount <= 0) return reason;
  return `${reason}（第 ${Math.max(1, Math.round(retryCount))} 次重试）`;
}

function hasNegotiationResult(stepKey) {
  return Boolean(
    resolveNegotiationWinner(stepKey)
    || resolveNegotiationVeto(stepKey)
    || resolveNegotiationRebid(stepKey)
  );
}

function resolveNegotiationBudget(stepKey) {
  const payload = resolveStepNegotiation(stepKey);
  if (!payload?.budget || typeof payload.budget !== 'object') return null;
  return payload.budget;
}

function hasNegotiationBudget(stepKey) {
  const budget = resolveNegotiationBudget(stepKey);
  return Boolean(
    Number.isFinite(Number(budget?.spent))
    || Number.isFinite(Number(budget?.limit))
    || Number.isFinite(Number(budget?.remaining))
  );
}

function resolveNegotiationBudgetPercent(stepKey) {
  const budget = resolveNegotiationBudget(stepKey);
  const spent = Number(budget?.spent);
  const limit = Number(budget?.limit);
  if (!Number.isFinite(spent) || !Number.isFinite(limit) || limit <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((spent / limit) * 100)));
}

function resolveNegotiationBudgetText(stepKey) {
  const budget = resolveNegotiationBudget(stepKey);
  const spentText = formatBidCost(budget?.spent);
  const limitText = formatBidCost(budget?.limit);
  const remainingText = formatBidCost(budget?.remaining);
  return `预算 ${spentText} / ${limitText} · 剩余 ${remainingText}`;
}

function isActionRequired(step) {
  const stepKey = String(step?.key || '').trim().toLowerCase();
  if (stepKey === 'checkpoint') return false;
  return String(step?.status || '').trim().toLowerCase() === 'action_required' && Boolean(step?.action);
}
</script>

<style scoped>
.paper-workflow-panel {
  --workflow-panel-padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--bg);
  padding: var(--workflow-panel-padding);
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  align-content: start;
  gap: 8px;
}

.paper-workflow-progress-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  margin: 2px 0 4px;
  padding: 0;
}

.paper-workflow-progress-title {
  margin: 0;
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
}

.paper-workflow-progress-text {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
}

.paper-workflow-progress-track {
  height: 8px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  overflow: hidden;
}

.paper-workflow-progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.2s ease;
}

.paper-workflow-progress-stop-btn {
  width: 26px;
  height: 26px;
  border: 1px solid var(--line-2);
  border-radius: 999px;
  background: var(--bg);
  color: var(--accent);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
  padding: 0;
}

.paper-workflow-progress-stop-btn svg {
  width: 14px;
  height: 14px;
}

.paper-workflow-progress-stop-btn:hover:not(:disabled) {
  background: var(--panel);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line-2));
}

.paper-workflow-progress-stop-btn:disabled {
  color: var(--muted);
  border-color: var(--line);
  background: var(--panel);
  cursor: not-allowed;
}

.paper-workflow-step-list {
  display: grid;
  align-content: start;
  grid-auto-rows: max-content;
  gap: 9px;
  margin: 0;
  padding-top: 4px;
}

.paper-workflow-step-item {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  padding: 8px 11px;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  align-items: start;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}

.paper-workflow-step-item.is-active,
.paper-workflow-step-item.is-paused {
  border-color: var(--line-2);
  background: var(--bg);
}

.paper-workflow-step-item.is-failed {
  border-color: var(--accent);
}

.paper-workflow-step-indicator {
  font-size: 12px;
  color: var(--muted);
  line-height: 1;
  min-height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.paper-workflow-step-item.is-active .paper-workflow-step-indicator {
  color: var(--accent);
}

.paper-workflow-step-main {
  --step-trace-edge-offset: 22px;
  --step-trace-content-indent: 10px;
  --step-trace-right-gutter: 10px;
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 6px;
}

.paper-workflow-step-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  min-height: 20px;
  gap: 6px;
}

.paper-workflow-step-label {
  margin: 0;
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-step-toggle-btn {
  width: 20px;
  height: 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  cursor: pointer;
  transition: border-color 0.2s ease, background-color 0.2s ease, color 0.2s ease;
}

.paper-workflow-step-toggle-btn svg {
  width: 12px;
  height: 12px;
  display: block;
  flex: 0 0 auto;
}

.paper-workflow-step-toggle-btn:hover {
  background: var(--panel);
  border-color: var(--line-2);
  color: var(--text);
}

.paper-workflow-step-toggle-btn:focus-visible {
  outline: 1px solid var(--line-2);
  outline-offset: 1px;
}

.paper-workflow-step-toggle-btn.is-collapsed {
  border-color: var(--line-2);
  color: var(--text);
}

.paper-workflow-negotiation {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  padding: 8px var(--step-trace-right-gutter);
  display: grid;
  align-content: start;
  gap: 6px;
  margin-left: calc(var(--step-trace-edge-offset) * -1);
}

.paper-workflow-negotiation-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}

.paper-workflow-negotiation-round {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
}

.paper-workflow-negotiation-status {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0 6px;
  line-height: 18px;
  font-size: 10px;
  color: var(--muted);
  background: var(--panel);
}

.paper-workflow-negotiation-status.is-bidding {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
}

.paper-workflow-negotiation-status.is-awarded {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 40%, var(--line));
}

.paper-workflow-negotiation-status.is-vetoed,
.paper-workflow-negotiation-status.is-rebid {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
}

.paper-workflow-negotiation-task {
  margin: 0;
  font-size: 11px;
  color: var(--text);
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-negotiation-flow {
  border: 1px dashed var(--line-2);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--muted);
  font-size: 10px;
  line-height: 20px;
  min-height: 22px;
  padding: 0 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  max-width: 100%;
}

.paper-workflow-negotiation-arrow {
  color: var(--text);
}

.paper-workflow-negotiation-bids {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.paper-workflow-negotiation-bid {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  padding: 6px;
  display: grid;
  align-content: start;
  gap: 4px;
  min-width: 0;
}

.paper-workflow-negotiation-bid.is-winner {
  border-color: color-mix(in srgb, var(--success) 40%, var(--line));
  background: color-mix(in srgb, var(--success) 8%, var(--bg));
}

.paper-workflow-negotiation-bid.is-vetoed {
  border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
  background: color-mix(in srgb, var(--accent) 8%, var(--bg));
}

.paper-workflow-negotiation-bid-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
}

.paper-workflow-negotiation-bid-title {
  margin: 0;
  font-size: 10px;
  color: var(--text);
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-negotiation-bid-badge {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0 6px;
  line-height: 18px;
  font-size: 10px;
  color: var(--muted);
  background: var(--bg);
}

.paper-workflow-negotiation-bid-badge.is-winner {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 38%, var(--line));
}

.paper-workflow-negotiation-bid-badge.is-vetoed {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
}

.paper-workflow-negotiation-bid-metrics {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
  line-height: 1.4;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-negotiation-result {
  display: grid;
  align-content: start;
  gap: 3px;
}

.paper-workflow-negotiation-result-item {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
  line-height: 1.4;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-negotiation-result-item.is-winner {
  color: var(--success);
}

.paper-workflow-negotiation-result-item.is-veto,
.paper-workflow-negotiation-result-item.is-rebid {
  color: var(--accent);
}

.paper-workflow-negotiation-budget {
  display: grid;
  align-content: start;
  gap: 4px;
}

.paper-workflow-negotiation-budget-track {
  height: 6px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--panel);
  overflow: hidden;
}

.paper-workflow-negotiation-budget-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.2s ease;
}

.paper-workflow-negotiation-budget-text {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
}

.paper-workflow-trace-list {
  display: grid;
  align-content: start;
  gap: 6px;
  margin-left: calc(var(--step-trace-edge-offset) * -1);
}

.paper-workflow-negotiation,
.paper-workflow-trace-list {
  margin-right: 0;
  min-width: 0;
  width: calc(100% + var(--step-trace-edge-offset));
  max-width: calc(100% + var(--step-trace-edge-offset));
  box-sizing: border-box;
}

.paper-workflow-trace-item {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg);
  padding: 6px 74px 6px var(--step-trace-content-indent);
  display: grid;
  align-content: start;
  gap: 4px;
  position: relative;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}

.paper-workflow-trace-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  align-items: center;
}

.paper-workflow-trace-title {
  margin: 0;
  font-size: 10px;
  color: var(--muted);
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-trace-badge {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0 6px;
  font-size: 10px;
  line-height: 18px;
  color: var(--muted);
  background: var(--panel);
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
}

.paper-workflow-trace-badge.is-active {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
}

.paper-workflow-trace-badge.is-done {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 40%, var(--line));
}

.paper-workflow-trace-badge.is-failed {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
}

.paper-workflow-trace-detail {
  margin: 0;
  font-size: 11px;
  color: var(--text);
  line-height: 1.45;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.paper-workflow-action-btn {
  height: 30px;
  font-size: 11px;
  padding: 0 10px;
  justify-self: center;
}

@media (max-width: 980px) {
  .paper-workflow-panel {
    min-height: auto;
    height: auto;
  }

  .paper-workflow-step-list {
    max-height: none;
  }
}

@media (max-width: 768px) {
  .paper-workflow-negotiation-bids {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
