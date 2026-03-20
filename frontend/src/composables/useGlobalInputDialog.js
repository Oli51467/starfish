import { reactive, readonly } from 'vue';

const INITIAL_STATE = {
  open: false,
  title: '',
  message: '',
  placeholder: '',
  confirmText: '确认',
  cancelText: '取消',
  value: '',
  errorMessage: '',
  required: true,
  requiredMessage: '请输入内容。',
  maxLength: 120
};

const dialogState = reactive({ ...INITIAL_STATE });
let pendingResolver = null;
let pendingValidator = null;

function resetDialogState() {
  Object.assign(dialogState, INITIAL_STATE);
  pendingValidator = null;
}

function resolveDialog(result) {
  const resolver = pendingResolver;
  pendingResolver = null;
  resetDialogState();
  if (typeof resolver === 'function') {
    resolver(result);
  }
}

function normalizeText(value) {
  return String(value ?? '').trim();
}

export function useGlobalInputDialog() {
  function askForInput(options = {}) {
    const title = normalizeText(options?.title) || '请输入内容';
    const message = normalizeText(options?.message);
    const placeholder = String(options?.placeholder || '').trim();
    const confirmText = normalizeText(options?.confirmText) || '确认';
    const cancelText = normalizeText(options?.cancelText) || '取消';
    const value = String(options?.initialValue || '');
    const required = options?.required !== false;
    const requiredMessage = normalizeText(options?.requiredMessage) || '请输入内容。';
    const maxLengthRaw = Number(options?.maxLength);
    const maxLength = Number.isFinite(maxLengthRaw) && maxLengthRaw > 0
      ? Math.min(500, Math.round(maxLengthRaw))
      : INITIAL_STATE.maxLength;

    if (typeof pendingResolver === 'function') {
      pendingResolver(null);
      pendingResolver = null;
    }

    pendingValidator = typeof options?.validate === 'function' ? options.validate : null;

    Object.assign(dialogState, {
      open: true,
      title,
      message,
      placeholder,
      confirmText,
      cancelText,
      value,
      errorMessage: '',
      required,
      requiredMessage,
      maxLength
    });

    return new Promise((resolve) => {
      pendingResolver = resolve;
    });
  }

  function updateInputValue(nextValue) {
    dialogState.value = String(nextValue ?? '');
    if (dialogState.errorMessage) {
      dialogState.errorMessage = '';
    }
  }

  function cancelInput() {
    resolveDialog(null);
  }

  function confirmInput() {
    const rawValue = String(dialogState.value || '');
    const value = rawValue.trim();

    if (dialogState.required && !value) {
      dialogState.errorMessage = dialogState.requiredMessage || '请输入内容。';
      return;
    }

    if (dialogState.maxLength > 0 && value.length > dialogState.maxLength) {
      dialogState.errorMessage = `输入内容不可超过 ${dialogState.maxLength} 个字符。`;
      return;
    }

    if (typeof pendingValidator === 'function') {
      const validationResult = pendingValidator(value);
      const validationMessage = normalizeText(validationResult);
      if (validationMessage) {
        dialogState.errorMessage = validationMessage;
        return;
      }
    }

    resolveDialog(value);
  }

  return {
    dialogState: readonly(dialogState),
    askForInput,
    updateInputValue,
    cancelInput,
    confirmInput
  };
}
