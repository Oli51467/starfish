<template>
  <Teleport to="body">
    <div
      v-if="dialogState.open"
      class="global-confirm-mask"
      role="presentation"
      @click.self="cancelConfirm"
    >
      <section
        class="global-confirm-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="global-confirm-title"
        aria-describedby="global-confirm-message"
      >
        <h3 id="global-confirm-title" class="global-confirm-title">{{ dialogState.title }}</h3>
        <p id="global-confirm-message" class="global-confirm-message">{{ dialogState.message }}</p>
        <div class="global-confirm-actions">
          <button class="btn mono" type="button" @click="cancelConfirm">
            {{ dialogState.cancelText }}
          </button>
          <button
            class="btn mono global-confirm-accept-btn"
            :class="{ 'is-danger': dialogState.danger }"
            type="button"
            @click="confirmConfirm"
          >
            {{ dialogState.confirmText }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { onBeforeUnmount, onMounted } from 'vue';

import { useGlobalConfirmDialog } from '../../composables/useGlobalConfirmDialog';

const { dialogState, cancelConfirm, confirmConfirm } = useGlobalConfirmDialog();

function onKeydown(event) {
  if (!dialogState.open) return;
  if (event.key !== 'Escape') return;
  cancelConfirm();
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown);
});
</script>
