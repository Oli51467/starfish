import { computed, ref } from 'vue';

import { authWithGithub, authWithGoogle, getAuthMe } from '../api';

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

function normalizeGithubAuthError(rawMessage) {
  const safe = String(rawMessage || '').trim();
  if (!safe) return 'GitHub 登录失败，请稍后重试。';

  const mapped = {
    empty_github_code: 'GitHub 登录参数缺失。',
    empty_github_state: 'GitHub 登录状态已失效，请重试。',
    invalid_github_state: 'GitHub 登录状态已失效，请重试。',
    invalid_github_code: 'GitHub 授权码无效或已过期，请重新登录。',
    github_email_not_verified: 'GitHub 账户缺少可用的已验证邮箱，请检查后重试。',
    github_login_not_configured: '请先配置 GitHub 登录。',
    github_token_exchange_failed: 'GitHub 登录失败，请稍后重试。',
    github_profile_request_failed: 'GitHub 登录失败，请稍后重试。',
    github_email_request_failed: 'GitHub 登录失败，请稍后重试。',
    invalid_github_access_token: 'GitHub 登录失败，请稍后重试。',
    github_access_token_missing: 'GitHub 登录失败，请稍后重试。',
    github_profile_incomplete: 'GitHub 账户信息不完整，请检查后重试。'
  };
  return mapped[safe] || safe;
}

function applySession(session) {
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
    errorMessage.value = '登录已失效，请重新登录。';
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
    return applySession(session);
  } catch (error) {
    clearSession();
    errorMessage.value = error?.message || 'Google 登录失败，请稍后重试。';
    throw error;
  } finally {
    loading.value = false;
  }
}

async function loginWithGithubCode(code, state) {
  const safeCode = String(code || '').trim();
  const safeState = String(state || '').trim();
  if (!safeCode) {
    errorMessage.value = 'GitHub 登录参数缺失。';
    throw new Error(errorMessage.value);
  }
  if (!safeState) {
    errorMessage.value = 'GitHub 登录状态已失效，请重试。';
    throw new Error(errorMessage.value);
  }

  loading.value = true;
  errorMessage.value = '';

  try {
    const session = await authWithGithub(safeCode, safeState);
    return applySession(session);
  } catch (error) {
    clearSession();
    const friendly = normalizeGithubAuthError(error?.message);
    errorMessage.value = friendly;
    throw new Error(friendly);
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
    loginWithGithubCode,
    logout
  };
}
