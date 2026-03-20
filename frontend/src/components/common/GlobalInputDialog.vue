<template>
  <Teleport to="body">
    <div
      v-if="dialogState.open"
      class="global-confirm-mask"
      role="presentation"
      @click.self="cancelInput"
    >
      <section
        class="global-confirm-card global-input-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="global-input-title"
        aria-describedby="global-input-message"
      >
        <h3 id="global-input-title" class="global-confirm-title">{{ dialogState.title }}</h3>
        <p v-if="dialogState.message" id="global-input-message" class="global-confirm-message">{{ dialogState.message }}</p>
        <input
          ref="inputRef"
          class="text-input mono global-input-field"
          type="text"
          :value="dialogState.value"
          :maxlength="dialogState.maxLength || undefined"
          :placeholder="dialogState.placeholder"
          @input="updateInputValue($event.target.value)"
          @keydown.enter.prevent="confirmInput"
        />
        <p v-if="dialogState.errorMessage" class="global-input-error mono">{{ dialogState.errorMessage }}</p>
        <div class="global-confirm-actions">
          <button class="btn mono" type="button" @click="cancelInput">
            {{ dialogState.cancelText }}
          </button>
          <button
            class="btn mono global-confirm-accept-btn"
            type="button"
            @click="confirmInput"
          >
            {{ dialogState.confirmText }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { useGlobalInputDialog } from '../../composables/useGlobalInputDialog';

const { dialogState, updateInputValue, cancelInput, confirmInput } = useGlobalInputDialog();
const inputRef = ref(null);

async function focusInput() {
  if (!dialogState.open) return;
  await nextTick();
  if (!inputRef.value?.focus) return;
  inputRef.value.focus();
  if (inputRef.value?.select) {
    inputRef.value.select();
  }
}

function onKeydown(event) {
  if (!dialogState.open) return;
  if (event.key !== 'Escape') return;
  cancelInput();
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown);
});

watch(
  () => dialogState.open,
  async (opened) => {
    if (!opened) return;
    await focusInput();
  }
);
</script>
