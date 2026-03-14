<template>
  <div class="custom-select" ref="rootRef">
    <button
      :id="id"
      class="custom-select-trigger mono"
      type="button"
      :aria-label="ariaLabel"
      :aria-expanded="open ? 'true' : 'false'"
      @click="toggle"
    >
      <span :class="{ 'is-placeholder': !hasSelection }">{{ selectedLabel }}</span>
      <span class="custom-select-caret" aria-hidden="true">▾</span>
    </button>

    <ul v-if="open" class="custom-select-menu" role="listbox">
      <li v-for="option in options" :key="option.value">
        <button
          class="custom-select-option mono"
          :class="{ 'is-selected': option.value === modelValue }"
          type="button"
          role="option"
          :aria-selected="option.value === modelValue ? 'true' : 'false'"
          @click="selectOption(option.value)"
        >
          {{ option.label }}
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

const props = defineProps({
  id: {
    type: String,
    default: ''
  },
  modelValue: {
    type: String,
    required: true
  },
  options: {
    type: Array,
    required: true
  },
  ariaLabel: {
    type: String,
    default: '选择输入类型'
  },
  placeholder: {
    type: String,
    default: '请选择'
  }
});

const emit = defineEmits(['update:modelValue']);

const open = ref(false);
const rootRef = ref(null);

const hasSelection = computed(() => props.options.some((item) => item.value === props.modelValue));

const selectedLabel = computed(() => {
  const selected = props.options.find((item) => item.value === props.modelValue);
  return selected?.label || props.placeholder;
});

function toggle() {
  open.value = !open.value;
}

function close() {
  open.value = false;
}

function selectOption(value) {
  emit('update:modelValue', value);
  close();
}

function handleDocumentClick(event) {
  if (!rootRef.value?.contains(event.target)) {
    close();
  }
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    close();
  }
}

onMounted(() => {
  document.addEventListener('mousedown', handleDocumentClick);
  document.addEventListener('keydown', handleKeydown);
});

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleDocumentClick);
  document.removeEventListener('keydown', handleKeydown);
});
</script>
