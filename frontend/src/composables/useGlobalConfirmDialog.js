import { reactive, readonly } from 'vue';

const INITIAL_STATE = {
  open: false,
  title: '',
  message: '',
  confirmText: '确认',
  cancelText: '取消',
  danger: false
};

const dialogState = reactive({ ...INITIAL_STATE });
let pendingResolver = null;

function resetDialogState() {
  Object.assign(dialogState, INITIAL_STATE);
}

function resolveDialog(result) {
  const resolver = pendingResolver;
  pendingResolver = null;
  resetDialogState();
  if (typeof resolver === 'function') {
    resolver(Boolean(result));
  }
}

export function useGlobalConfirmDialog() {
  function askForConfirm(options = {}) {
    const title = String(options?.title || '').trim() || '确认操作';
    const message = String(options?.message || '').trim() || '是否继续执行该操作？';
    const confirmText = String(options?.confirmText || '').trim() || '确认';
    const cancelText = String(options?.cancelText || '').trim() || '取消';
    const danger = Boolean(options?.danger);

    if (typeof pendingResolver === 'function') {
      pendingResolver(false);
      pendingResolver = null;
    }

    Object.assign(dialogState, {
      open: true,
      title,
      message,
      confirmText,
      cancelText,
      danger
    });

    return new Promise((resolve) => {
      pendingResolver = resolve;
    });
  }

  function cancelConfirm() {
    resolveDialog(false);
  }

  function confirmConfirm() {
    resolveDialog(true);
  }

  return {
    dialogState: readonly(dialogState),
    askForConfirm,
    cancelConfirm,
    confirmConfirm
  };
}
