import { computed, onUnmounted, ref } from 'vue';

import {
  createPipelineWebSocket,
  getPipelineReport,
  resumePipelineSession,
  startPipelineSession,
  stopPipelineSession
} from '../api';

const STEP_ORDER = [
  { id: 'planner', label: 'Planner' },
  { id: 'search', label: 'Search' },
  { id: 'graph_build', label: 'Graph Build' },
  { id: 'checkpoint_1', label: 'Checkpoint 1' },
  { id: 'parallel', label: 'Deep Analysis' },
  { id: 'synthesizer', label: 'Synthesize' },
  { id: 'checkpoint_2', label: 'Checkpoint 2' },
  { id: 'report', label: 'Report' },
  { id: 'save', label: 'Save' }
];

const NODE_ALIAS = {
  router: 'search'
};

function normalizeNodeId(rawNode) {
  const safe = String(rawNode || '').trim();
  return NODE_ALIAS[safe] || safe;
}

function createStepState() {
  return STEP_ORDER.map((step) => ({
    id: step.id,
    label: step.label,
    status: 'pending',
    summary: ''
  }));
}

export function usePipelineSession({
  accessTokenRef,
  onStepChange
} = {}) {
  const notifyStepChange = typeof onStepChange === 'function' ? onStepChange : () => {};

  const sessionId = ref('');
  const steps = ref(createStepState());
  const progress = ref(0);
  const messages = ref([]);
  const currentThinking = ref('');
  const currentNode = ref('');
  const isPaused = ref(false);
  const checkpointMessage = ref('');
  const checkpointNode = ref('');
  const countdown = ref(0);
  const finalReport = ref('');
  const running = ref(false);
  const status = ref('idle');
  const errorMessage = ref('');

  let ws = null;
  let countdownTimer = null;

  const activeStep = computed(() => {
    const runningStep = steps.value.find((item) => item.status === 'active' || item.status === 'paused');
    if (runningStep) return runningStep;
    const failedStep = steps.value.find((item) => item.status === 'failed');
    if (failedStep) return failedStep;
    const doneStep = [...steps.value].reverse().find((item) => item.status === 'done');
    return doneStep || steps.value[0];
  });

  function emitStepSignal() {
    const current = activeStep.value;
    if (!current) return;
    const index = Math.max(1, steps.value.findIndex((item) => item.id === current.id) + 1);
    notifyStepChange({
      index,
      total: steps.value.length,
      title: current.label
    });
  }

  function clearCountdown() {
    if (countdownTimer) {
      window.clearInterval(countdownTimer);
      countdownTimer = null;
    }
    countdown.value = 0;
  }

  function stopSocket() {
    if (ws) {
      ws.close();
      ws = null;
    }
  }

  function resetState() {
    clearCountdown();
    stopSocket();

    sessionId.value = '';
    steps.value = createStepState();
    progress.value = 0;
    messages.value = [];
    currentThinking.value = '';
    currentNode.value = '';
    isPaused.value = false;
    checkpointMessage.value = '';
    checkpointNode.value = '';
    finalReport.value = '';
    running.value = false;
    status.value = 'idle';
    errorMessage.value = '';
    emitStepSignal();
  }

  function pushMessage(payload) {
    messages.value.push({
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      type: String(payload?.type || 'summary'),
      node: String(payload?.node || '').trim(),
      content: String(payload?.content || '').trim()
    });
  }

  function updateStepStatus(nodeId, nextStatus, summary = '') {
    const normalized = normalizeNodeId(nodeId);
    const target = steps.value.find((item) => item.id === normalized);
    if (!target) return;

    if (nextStatus === 'active') {
      steps.value = steps.value.map((item) => {
        if (item.id === target.id) {
          return { ...item, status: 'active', summary: summary || item.summary };
        }
        if (item.status === 'active') {
          return { ...item, status: 'done' };
        }
        return item;
      });
      emitStepSignal();
      return;
    }

    target.status = nextStatus;
    if (summary) {
      target.summary = summary;
    }
    emitStepSignal();
  }

  function startCountdown(seconds) {
    clearCountdown();
    const safeSeconds = Math.max(0, Number(seconds) || 0);
    if (!safeSeconds) return;

    countdown.value = safeSeconds;
    countdownTimer = window.setInterval(() => {
      countdown.value -= 1;
      if (countdown.value <= 0) {
        clearCountdown();
        void resume('');
      }
    }, 1000);
  }

  async function refreshReport() {
    const safeSessionId = String(sessionId.value || '').trim();
    if (!safeSessionId) return;

    try {
      const payload = await getPipelineReport(safeSessionId, { accessToken: accessTokenRef?.value || '' });
      finalReport.value = String(payload?.report || '').trim();
    } catch {
      // keep websocket-driven state even if report endpoint is temporarily unavailable
    }
  }

  function handleNodeStart(event) {
    currentNode.value = normalizeNodeId(event?.node || '');
    currentThinking.value = '';
    updateStepStatus(event?.node, 'active');
    progress.value = Math.max(progress.value, Number(event?.progress) || 0);
  }

  function handleThinking(event) {
    const content = String(event?.content || '').trim();
    if (!content) return;
    currentNode.value = normalizeNodeId(event?.node || currentNode.value);
    currentThinking.value += content;
  }

  function handleNodeComplete(event) {
    const summary = String(event?.summary || '').trim();
    updateStepStatus(event?.node, 'done', summary);
    progress.value = Math.max(progress.value, Number(event?.progress) || 0);
    currentThinking.value = '';
    if (summary) {
      pushMessage({
        type: 'summary',
        node: normalizeNodeId(event?.node),
        content: summary
      });
    }
  }

  function handlePause(event) {
    isPaused.value = true;
    checkpointNode.value = normalizeNodeId(event?.checkpoint || '');
    checkpointMessage.value = String(event?.message || '').trim();
    updateStepStatus(checkpointNode.value, 'paused', checkpointMessage.value);
    startCountdown(Number(event?.timeout) || 30);
  }

  async function handleSessionComplete() {
    status.value = 'completed';
    running.value = false;
    isPaused.value = false;
    progress.value = 100;
    clearCountdown();
    await refreshReport();
  }

  function handleError(event) {
    status.value = 'failed';
    running.value = false;
    isPaused.value = false;
    clearCountdown();
    errorMessage.value = String(event?.error || event?.message || 'Pipeline 执行失败。').trim();
    const current = activeStep.value;
    if (current) {
      updateStepStatus(current.id, 'failed', errorMessage.value);
    }
    pushMessage({
      type: 'error',
      node: current?.id || currentNode.value,
      content: errorMessage.value
    });
  }

  function handleStopped() {
    status.value = 'stopped';
    running.value = false;
    isPaused.value = false;
    clearCountdown();
    pushMessage({
      type: 'stopped',
      node: currentNode.value,
      content: '流程已停止。'
    });
  }

  function handleEvent(event) {
    const eventType = String(event?.type || '').trim();
    if (!eventType) return;

    if (eventType === 'node_start') {
      handleNodeStart(event);
      return;
    }
    if (eventType === 'thinking') {
      handleThinking(event);
      return;
    }
    if (eventType === 'node_complete') {
      handleNodeComplete(event);
      return;
    }
    if (eventType === 'pause') {
      handlePause(event);
      return;
    }
    if (eventType === 'session_complete') {
      void handleSessionComplete();
      return;
    }
    if (eventType === 'error') {
      handleError(event);
      return;
    }
    if (eventType === 'stopped') {
      handleStopped();
    }
  }

  function bindWebSocket(nextSessionId) {
    const token = String(accessTokenRef?.value || '').trim();
    ws = createPipelineWebSocket(nextSessionId, token);

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleEvent(payload);
      } catch {
        // ignore malformed events
      }
    };

    ws.onerror = () => {
      if (status.value === 'completed' || status.value === 'stopped') return;
      errorMessage.value = '实时连接中断，请刷新后重试。';
    };

    ws.onclose = () => {
      ws = null;
    };
  }

  async function start(seedPayload) {
    resetState();
    running.value = true;
    status.value = 'running';

    const payload = {
      input_type: String(seedPayload?.input_type || '').trim() || 'domain',
      input_value: String(seedPayload?.input_value || '').trim(),
      paper_range_years: seedPayload?.paper_range_years || null,
      quick_mode: Boolean(seedPayload?.quick_mode)
    };

    try {
      const created = await startPipelineSession(payload, { accessToken: accessTokenRef?.value || '' });
      const safeSessionId = String(created?.session_id || '').trim();
      if (!safeSessionId) {
        throw new Error('pipeline_session_missing');
      }
      sessionId.value = safeSessionId;
      bindWebSocket(safeSessionId);
    } catch (error) {
      running.value = false;
      status.value = 'failed';
      errorMessage.value = error?.message || '启动 Pipeline 失败。';
    }
  }

  async function resume(feedback = '') {
    const safeSessionId = String(sessionId.value || '').trim();
    if (!safeSessionId) return;

    clearCountdown();
    isPaused.value = false;

    try {
      const result = await resumePipelineSession(safeSessionId, feedback, {
        accessToken: accessTokenRef?.value || ''
      });
      if (!result?.resumed) {
        return;
      }
      if (checkpointNode.value) {
        updateStepStatus(checkpointNode.value, 'active');
      }
      checkpointNode.value = '';
      checkpointMessage.value = '';
      currentThinking.value = '';
    } catch (error) {
      errorMessage.value = error?.message || '恢复执行失败。';
      isPaused.value = true;
    }
  }

  async function stop() {
    const safeSessionId = String(sessionId.value || '').trim();
    if (!safeSessionId) return;

    try {
      await stopPipelineSession(safeSessionId, {
        accessToken: accessTokenRef?.value || ''
      });
    } catch {
      // ignore stop call failure
    }
    handleStopped();
  }

  function dispose() {
    clearCountdown();
    stopSocket();
  }

  onUnmounted(() => {
    dispose();
  });

  return {
    sessionId,
    steps,
    progress,
    messages,
    currentThinking,
    currentNode,
    isPaused,
    checkpointMessage,
    countdown,
    finalReport,
    running,
    status,
    errorMessage,
    start,
    resume,
    stop,
    refreshReport,
    dispose
  };
}
