<template>
  <RouterView />
  <GlobalConfirmDialog />
  <GlobalInputDialog />
</template>

<script setup>
import { RouterView } from 'vue-router';

import GlobalConfirmDialog from './components/common/GlobalConfirmDialog.vue';
import GlobalInputDialog from './components/common/GlobalInputDialog.vue';
</script>
