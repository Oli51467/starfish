import { ref } from 'vue';

const activeView = ref('input');

const navItems = [
  { key: 'input', label: '输入' },
  { key: 'map', label: '领域地图' },
  { key: 'reading', label: '必读清单' },
  { key: 'gaps', label: '研究空白' },
  { key: 'lineage', label: '论文血缘树' }
];

export function useSessionStore() {
  return {
    activeView,
    navItems
  };
}
