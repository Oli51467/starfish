import { reactive, readonly } from 'vue';

const INITIAL_STATE = {
  open: false,
  title: '',
  message: '',
  placeholder: '',
  inputType: 'text',
  optionItems: [],
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

function normalizeOptionItems(rawOptions) {
  if (!Array.isArray(rawOptions)) return [];
  const items = [];
  for (const option of rawOptions) {
    if (option === null || option === undefined) continue;
    if (typeof option === 'string' || typeof option === 'number') {
      const normalizedValue = String(option).trim();
      if (!normalizedValue) continue;
      items.push({ label: normalizedValue, value: normalizedValue });
      continue;
    }
    if (typeof option === 'object') {
      const value = String(option.value ?? '').trim();
      const label = String(option.label ?? value).trim();
      if (!value || !label) continue;
      items.push({ label, value });
    }
  }
  return items;
}

export function useGlobalInputDialog() {
  function askForInput(options = {}) {
    const title = normalizeText(options?.title) || '请输入内容';
    const message = normalizeText(options?.message);
    const placeholder = String(options?.placeholder || '').trim();
    const confirmText = normalizeText(options?.confirmText) || '确认';
    const cancelText = normalizeText(options?.cancelText) || '取消';
    const required = options?.required !== false;
    const requiredMessage = normalizeText(options?.requiredMessage) || '请输入内容。';
    const maxLengthRaw = Number(options?.maxLength);
    const maxLength = Number.isFinite(maxLengthRaw) && maxLengthRaw > 0
      ? Math.min(500, Math.round(maxLengthRaw))
      : INITIAL_STATE.maxLength;
    const optionItems = normalizeOptionItems(options?.options);
    const inputType = optionItems.length ? 'select' : 'text';
    const initialRawValue = String(options?.initialValue || '');
    const selectValue = optionItems.some((item) => item.value === initialRawValue)
      ? initialRawValue
      : String(optionItems[0]?.value || '');
    const value = inputType === 'select' ? selectValue : initialRawValue;

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
      inputType,
      optionItems,
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
    const isSelect = String(dialogState.inputType || '').trim().toLowerCase() === 'select';
    const optionItems = Array.isArray(dialogState.optionItems) ? dialogState.optionItems : [];
    const optionValues = new Set(optionItems.map((item) => String(item.value || '').trim()).filter(Boolean));

    if (dialogState.required && !value) {
      dialogState.errorMessage = dialogState.requiredMessage || '请输入内容。';
      return;
    }

    if (isSelect && value && !optionValues.has(value)) {
      dialogState.errorMessage = dialogState.requiredMessage || '请选择有效选项。';
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
