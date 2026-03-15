<template>
  <div class="header-auth">
    <p v-if="!googleClientId" class="header-auth-tip mono">请配置 Google 登录</p>

    <template v-else-if="isAuthenticated">
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

    <div v-else class="header-google-entry">
      <div ref="googleButtonRef" class="header-google-button" />
      <p v-if="loginErrorMessage" class="header-auth-error mono">{{ loginErrorMessage }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useAuthStore } from '../../stores/authStore';

const googleClientId = String(import.meta.env.VITE_GOOGLE_CLIENT_ID || '').trim();
const googleButtonRef = ref(null);
const userMenuRef = ref(null);
const userMenuOpen = ref(false);
const scriptLoadError = ref('');
const router = useRouter();
const route = useRoute();
const { user, isAuthenticated, loading, errorMessage, loginWithGoogleCredential, logout } = useAuthStore();

const userEmail = computed(() => String(user.value?.email || '').trim());
const avatarInitial = computed(() => userEmail.value.slice(0, 1).toUpperCase() || 'U');
const isHistoryPage = computed(() => route.name === 'research-history');
const loginErrorMessage = computed(() => {
  return scriptLoadError.value || errorMessage.value;
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
    if (googleButtonRef.value) {
      googleButtonRef.value.innerHTML = '';
    }
  } catch {
    // error message is managed by authStore
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
  if (route.name !== 'home') {
    void router.push({ name: 'home' });
  }
}

function openResearchHistory() {
  closeUserMenu();
  if (isHistoryPage.value) return;
  void router.push({ name: 'research-history' });
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
