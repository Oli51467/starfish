<template>
  <main class="auth-callback-page">
    <article class="auth-callback-card panel">
      <p class="auth-callback-kicker mono">GitHub OAuth</p>
      <h1 class="auth-callback-title">{{ title }}</h1>
      <p class="auth-callback-detail mono">{{ detail }}</p>
      <button v-if="showBackButton" class="btn btn-accent mono auth-callback-btn" type="button" @click="goHome">
        返回首页
      </button>
    </article>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useAuthStore } from '../stores/authStore';

const route = useRoute();
const router = useRouter();
const { loginWithGithubCode } = useAuthStore();

const title = ref('正在完成 GitHub 登录...');
const detail = ref('请稍候，正在校验授权信息。');
const loading = ref(true);

const showBackButton = computed(() => !loading.value);

function normalizeGithubCallbackError(rawMessage) {
  const safe = String(rawMessage || '').trim();
  if (!safe) return 'GitHub 登录失败，请稍后重试。';
  if (safe === 'invalid_github_state') return 'GitHub 登录状态已失效，请重新发起登录。';
  if (safe === 'invalid_github_code') return 'GitHub 授权码无效或已过期，请重新登录。';
  if (safe === 'github_email_not_verified') return 'GitHub 账户缺少可用的已验证邮箱，请检查后重试。';
  if (safe === 'github_login_not_configured') return '服务端尚未配置 GitHub 登录。';
  if (safe === 'github_profile_incomplete') return 'GitHub 账户信息不完整，请检查后重试。';
  if (safe.startsWith('github_') || safe.startsWith('invalid_github_')) {
    return 'GitHub 登录失败，请稍后重试。';
  }
  return safe;
}

function goHome() {
  void router.replace({ name: 'home' });
}

onMounted(async () => {
  const oauthError = String(route.query.error || '').trim();
  if (oauthError) {
    const description = String(route.query.error_description || '').trim();
    title.value = 'GitHub 登录失败';
    detail.value = description || oauthError;
    loading.value = false;
    return;
  }

  const code = String(route.query.code || '').trim();
  const state = String(route.query.state || '').trim();
  if (!code || !state) {
    title.value = 'GitHub 登录失败';
    detail.value = '缺少授权参数，请重新登录。';
    loading.value = false;
    return;
  }

  try {
    await loginWithGithubCode(code, state);
    title.value = '登录成功';
    detail.value = '正在返回首页...';
    await router.replace({ name: 'home' });
  } catch (error) {
    title.value = 'GitHub 登录失败';
    detail.value = normalizeGithubCallbackError(error?.message);
    loading.value = false;
  }
});
</script>

<style scoped>
.auth-callback-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at 10% 20%, rgba(245, 245, 245, 0.9), transparent 45%),
    radial-gradient(circle at 85% 10%, rgba(235, 235, 235, 0.85), transparent 42%),
    var(--bg);
}

.auth-callback-card {
  width: min(460px, 100%);
  padding: 22px 20px;
  display: grid;
  gap: 10px;
  justify-items: center;
  text-align: center;
}

.auth-callback-kicker {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}

.auth-callback-title {
  margin: 0;
  font-size: 24px;
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 600;
  color: var(--text);
}

.auth-callback-detail {
  margin: 0;
  color: var(--muted);
  line-height: 1.5;
  font-size: 12px;
}

.auth-callback-btn {
  margin-top: 6px;
}
</style>
