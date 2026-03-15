import { computed, ref } from 'vue';

import { authWithGoogle, getAuthMe } from '../api';

const ACCESS_TOKEN_STORAGE_KEY = 'starfish.access_token';

const user = ref(null);
const accessToken = ref('');
const loading = ref(false);
const initialized = ref(false);
const errorMessage = ref('');

const isAuthenticated = computed(() => {
  return Boolean(accessToken.value && user.value?.id && user.value?.email);
});

function persistToken(token) {
  try {
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
  } catch {
    // Ignore localStorage write errors.
  }
}

function readPersistedToken() {
  try {
    return String(localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY) || '').trim();
  } catch {
    return '';
  }
}

function clearPersistedToken() {
  try {
    localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    // Ignore localStorage remove errors.
  }
}

function clearSession({ removeStorage = true } = {}) {
  user.value = null;
  accessToken.value = '';
  if (removeStorage) {
    clearPersistedToken();
  }
}

async function loadSession() {
  if (initialized.value) return;

  loading.value = true;
  errorMessage.value = '';

  const token = readPersistedToken();
  if (!token) {
    clearSession({ removeStorage: false });
    initialized.value = true;
    loading.value = false;
    return;
  }

  accessToken.value = token;
  try {
    user.value = await getAuthMe(token);
  } catch {
    clearSession();
    errorMessage.value = '登录已失效，请重新使用 Google 登录。';
  } finally {
    initialized.value = true;
    loading.value = false;
  }
}

async function loginWithGoogleCredential(credential) {
  const rawCredential = String(credential || '').trim();
  if (!rawCredential) {
    errorMessage.value = 'Google 登录凭证为空。';
    throw new Error(errorMessage.value);
  }

  loading.value = true;
  errorMessage.value = '';

  try {
    const session = await authWithGoogle(rawCredential);
    const token = String(session?.access_token || '').trim();
    const profile = session?.user || null;
    if (!token || !profile?.id || !profile?.email) {
      throw new Error('登录响应无效，请重试。');
    }
    accessToken.value = token;
    user.value = profile;
    persistToken(token);
    initialized.value = true;
    return profile;
  } catch (error) {
    clearSession();
    errorMessage.value = error?.message || 'Google 登录失败，请稍后重试。';
    throw error;
  } finally {
    loading.value = false;
  }
}

function logout() {
  clearSession();
  initialized.value = true;
  errorMessage.value = '';
}

export function useAuthStore() {
  return {
    user,
    accessToken,
    isAuthenticated,
    loading,
    initialized,
    errorMessage,
    loadSession,
    loginWithGoogleCredential,
    logout
  };
}
