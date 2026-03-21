import { computed, ref } from 'vue';

import { generateMap, getMap, getTask } from '../api';

const mapInput = ref({
  input_type: '',
  input_value: '',
  paper_range_years: '10',
  quick_mode: true,
  depth: 2
});

const task = ref(null);
const mapData = ref(null);
const loading = ref(false);
const errorMessage = ref('');

let pollingSession = 0;

function stopPolling() {
  pollingSession += 1;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchMapById(mapId) {
  mapData.value = await getMap(mapId);
}

async function pollTask(taskId) {
  const sessionId = ++pollingSession;

  while (sessionId === pollingSession) {
    let latestTask;
    try {
      latestTask = await getTask(taskId);
    } catch (error) {
      if (sessionId !== pollingSession) return;
      loading.value = false;
      errorMessage.value = error.message || '任务轮询失败。';
      return;
    }

    if (sessionId !== pollingSession) {
      return;
    }

    task.value = latestTask;

    if (latestTask.status === 'completed' && latestTask.result_id) {
      try {
        await fetchMapById(latestTask.result_id);
      } catch (error) {
        if (sessionId !== pollingSession) return;
        loading.value = false;
        errorMessage.value = error.message || '获取地图结果失败。';
        return;
      }
      if (sessionId === pollingSession) {
        loading.value = false;
      }
      return;
    }

    if (latestTask.status === 'failed') {
      loading.value = false;
      errorMessage.value = latestTask.error || '任务执行失败。';
      return;
    }

    await sleep(800);
  }
}

async function startMapGeneration() {
  if (loading.value || !mapInput.value.input_value.trim() || !String(mapInput.value.input_type || '').trim()) return;

  loading.value = true;
  errorMessage.value = '';
  stopPolling();

  try {
    const created = await generateMap({
      input_type: mapInput.value.input_type,
      input_value: mapInput.value.input_value.trim(),
      depth: Math.min(4, Math.max(1, Number(mapInput.value.depth) || 2))
    });

    task.value = { ...created, progress: 0 };
    void pollTask(created.task_id);
  } catch (error) {
    loading.value = false;
    errorMessage.value = error.message || '创建任务失败。';
  }
}

const mapId = computed(() => mapData.value?.map_id || task.value?.result_id || '');

export function useMapStore() {
  return {
    mapInput,
    task,
    mapData,
    mapId,
    loading,
    errorMessage,
    startMapGeneration,
    fetchMapById,
    stopPolling
  };
}
