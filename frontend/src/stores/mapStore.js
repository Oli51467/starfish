import { computed, ref } from 'vue';

import { generateMap, getMap, getTask } from '../api';

const mapInput = ref({
  input_type: 'arxiv_id',
  input_value: '',
  depth: 2
});

const task = ref(null);
const mapData = ref(null);
const loading = ref(false);
const errorMessage = ref('');

let pollingTimer = null;

function stopPolling() {
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

async function fetchMapById(mapId) {
  mapData.value = await getMap(mapId);
}

async function startMapGeneration() {
  if (loading.value || !mapInput.value.input_value.trim()) return;

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

    pollingTimer = setInterval(async () => {
      if (!task.value?.task_id) return;
      try {
        const latest = await getTask(task.value.task_id);
        task.value = latest;

        if (latest.status === 'completed' && latest.result_id) {
          stopPolling();
          await fetchMapById(latest.result_id);
          loading.value = false;
        }

        if (latest.status === 'failed') {
          stopPolling();
          loading.value = false;
          errorMessage.value = latest.error || '任务执行失败。';
        }
      } catch (error) {
        stopPolling();
        loading.value = false;
        errorMessage.value = error.message || '任务轮询失败。';
      }
    }, 800);
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
