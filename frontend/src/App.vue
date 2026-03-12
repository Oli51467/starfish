<template>
  <div class="app">
    <AppHeader />

    <main class="workspace workspace-single">
      <InputView />
    </main>
  </div>
</template>

<script setup>
import AppHeader from './components/layout/AppHeader.vue';
import InputView from './views/InputView.vue';
</script>
