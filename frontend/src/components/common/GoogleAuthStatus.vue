<template>
  <div class="header-auth">
    <template v-if="isAuthenticated">
      <div ref="userMenuRef" class="header-user-menu">
        <button
          class="header-user-pill header-user-trigger"
          type="button"
          :title="userEmail"
          :aria-expanded="userMenuOpen ? 'true' : 'false'"
          aria-haspopup="menu"
          @click="toggleUserMenu"
        >
          <img v-if="user?.picture" class="header-user-avatar" :src="user.picture" :alt="userEmail" />
          <span v-else class="header-user-avatar-fallback mono">{{ avatarInitial }}</span>
          <span class="header-user-email mono">{{ userEmail }}</span>
          <span class="header-user-caret" :class="{ 'is-open': userMenuOpen }" aria-hidden="true">▾</span>
        </button>

        <div v-if="userMenuOpen" class="header-user-dropdown panel" role="menu">
          <button
            class="header-user-dropdown-item mono"
            :class="{ 'is-disabled': isCollectionWorkbenchPage }"
            type="button"
            role="menuitem"
            :disabled="isCollectionWorkbenchPage"
            @click="openCollectionWorkbench"
          >
            我的论文
          </button>
          <button
            class="header-user-dropdown-item mono"
            :class="{ 'is-disabled': isHistoryPage }"
            type="button"
            role="menuitem"
            :disabled="isHistoryPage"
            @click="openResearchHistory"
          >
            研究历史
          </button>
          <button class="header-user-dropdown-item mono" type="button" role="menuitem" @click="handleLogout">
            退出登录
          </button>
        </div>
      </div>
    </template>

    <div v-else class="header-auth-entry">
      <p v-if="!googleClientId" class="header-auth-tip mono">未配置 Google 登录，可使用 GitHub 登录</p>
      <div class="header-auth-options">
        <div v-if="googleClientId" ref="googleButtonRef" class="header-google-button" />
        <button
          class="header-github-auth-btn mono"
          type="button"
          :disabled="loading || githubLoading"
          @click="startGithubLogin"
        >
          <span class="header-github-auth-icon" aria-hidden="true">
            <svg viewBox="0 0 16 16">
              <path
                fill="currentColor"
                d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49C4 14.09 3.48 13.73 3.32 13.5c-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.01.08-2.11 0 0 .67-.21 2.2.82a7.7 7.7 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.91.08 2.11.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.19 0 .21.15.46.55.38A8 8 0 0 0 16 8c0-4.42-3.58-8-8-8Z"
              />
            </svg>
          </span>
          <span>{{ githubButtonText }}</span>
        </button>
      </div>
      <p v-if="loginErrorMessage" class="header-auth-error mono">{{ loginErrorMessage }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { getGithubAuthorizeUrl } from '../../api';
import { useAuthStore } from '../../stores/authStore';
import { useCollectionStore } from '../../stores/collectionStore';

const googleClientId = String(import.meta.env.VITE_GOOGLE_CLIENT_ID || '').trim();
const googleButtonRef = ref(null);
const userMenuRef = ref(null);
const userMenuOpen = ref(false);
const scriptLoadError = ref('');
const githubLoginError = ref('');
const githubLoading = ref(false);
const router = useRouter();
const route = useRoute();
const { user, isAuthenticated, loading, errorMessage, loginWithGoogleCredential, logout } = useAuthStore();
const { clearCollectionStoreState } = useCollectionStore();

const userEmail = computed(() => String(user.value?.email || '').trim());
const avatarInitial = computed(() => userEmail.value.slice(0, 1).toUpperCase() || 'U');
const isHistoryPage = computed(() => route.name === 'research-history');
const isCollectionWorkbenchPage = computed(() => route.name === 'collection-workbench');
const githubButtonText = computed(() => (githubLoading.value ? 'GitHub 登录中...' : '使用 GitHub 登录'));
const loginErrorMessage = computed(() => {
  return scriptLoadError.value || githubLoginError.value || errorMessage.value;
});

let gisScriptPromise = null;

function loadGoogleIdentityScript() {
  if (window.google?.accounts?.id) {
    return Promise.resolve();
  }
  if (gisScriptPromise) {
    return gisScriptPromise;
  }

  gisScriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-google-gis="true"]');
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error('google_script_load_failed')), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.dataset.googleGis = 'true';
    script.addEventListener('load', () => resolve(), { once: true });
    script.addEventListener('error', () => reject(new Error('google_script_load_failed')), { once: true });
    document.head.appendChild(script);
  });

  return gisScriptPromise;
}

async function handleCredentialResponse(response) {
  const credential = String(response?.credential || '').trim();
  if (!credential || loading.value) return;

  try {
    await loginWithGoogleCredential(credential);
    scriptLoadError.value = '';
    githubLoginError.value = '';
    if (googleButtonRef.value) {
      googleButtonRef.value.innerHTML = '';
    }
  } catch {
    // error message is managed by authStore
  }
}

function normalizeGithubLoginError(rawMessage) {
  const safe = String(rawMessage || '').trim();
  if (!safe) return 'GitHub 登录初始化失败，请稍后重试。';

  const mapped = {
    github_login_not_configured: '请先配置 GitHub 登录。',
    invalid_github_state: 'GitHub 登录状态已失效，请重试。',
    invalid_github_code: 'GitHub 授权码无效或已过期，请重新登录。',
    github_email_not_verified: 'GitHub 账户缺少可用的已验证邮箱，请检查后重试。',
    github_token_exchange_failed: 'GitHub 登录初始化失败，请稍后重试。',
    github_profile_request_failed: 'GitHub 登录初始化失败，请稍后重试。',
    github_email_request_failed: 'GitHub 登录初始化失败，请稍后重试。',
    invalid_github_access_token: 'GitHub 登录初始化失败，请稍后重试。',
    github_access_token_missing: 'GitHub 登录初始化失败，请稍后重试。',
    github_profile_incomplete: 'GitHub 账户信息不完整，请检查后重试。'
  };
  return mapped[safe] || 'GitHub 登录初始化失败，请稍后重试。';
}

async function startGithubLogin() {
  if (loading.value || githubLoading.value) return;
  githubLoading.value = true;
  githubLoginError.value = '';
  scriptLoadError.value = '';

  try {
    const payload = await getGithubAuthorizeUrl();
    const authorizeUrl = String(payload?.authorize_url || '').trim();
    if (!authorizeUrl) {
      throw new Error('GitHub 登录地址无效，请稍后重试。');
    }
    window.location.assign(authorizeUrl);
  } catch (error) {
    githubLoginError.value = normalizeGithubLoginError(error?.message);
  } finally {
    githubLoading.value = false;
  }
}

function closeUserMenu() {
  userMenuOpen.value = false;
}

function toggleUserMenu() {
  userMenuOpen.value = !userMenuOpen.value;
}

function handleOutsideClick(event) {
  if (!userMenuRef.value?.contains(event.target)) {
    closeUserMenu();
  }
}

function handleEscape(event) {
  if (event.key === 'Escape') {
    closeUserMenu();
  }
}

function handleLogout() {
  closeUserMenu();
  logout();
  clearCollectionStoreState();
  if (route.name !== 'home') {
    void router.push({ name: 'home' });
  }
}

function openResearchHistory() {
  closeUserMenu();
  if (isHistoryPage.value) return;
  void router.push({ name: 'research-history' });
}

function openCollectionWorkbench() {
  closeUserMenu();
  if (isCollectionWorkbenchPage.value) return;
  void router.push({ name: 'collection-workbench' });
}

function renderGoogleButton() {
  if (!googleClientId || isAuthenticated.value || !googleButtonRef.value) return;
  const googleApi = window.google?.accounts?.id;
  if (!googleApi) {
    scriptLoadError.value = 'Google 登录组件加载失败，请刷新重试。';
    return;
  }

  googleButtonRef.value.innerHTML = '';
  googleApi.initialize({
    client_id: googleClientId,
    callback: handleCredentialResponse
  });
  const buttonWidth = window.innerWidth <= 768 ? 176 : 220;
  googleApi.renderButton(googleButtonRef.value, {
    theme: 'outline',
    size: 'medium',
    shape: 'pill',
    text: 'signin_with',
    width: buttonWidth,
    locale: 'zh-CN'
  });
}

async function mountGoogleButton() {
  if (!googleClientId || isAuthenticated.value) return;
  try {
    await loadGoogleIdentityScript();
    await nextTick();
    renderGoogleButton();
    scriptLoadError.value = '';
  } catch {
    scriptLoadError.value = 'Google 登录组件加载失败，请检查网络后重试。';
  }
}

watch(isAuthenticated, (next) => {
  if (!next) {
    closeUserMenu();
    githubLoginError.value = '';
    void mountGoogleButton();
    return;
  }
  if (googleButtonRef.value) {
    googleButtonRef.value.innerHTML = '';
  }
});

onMounted(() => {
  document.addEventListener('mousedown', handleOutsideClick);
  document.addEventListener('keydown', handleEscape);
  void mountGoogleButton();
});

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleOutsideClick);
  document.removeEventListener('keydown', handleEscape);
});
</script>
