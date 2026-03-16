<template>
  <RouterView />
  <GlobalConfirmDialog />
</template>

<script setup>
import { RouterView } from 'vue-router';

import GlobalConfirmDialog from './components/common/GlobalConfirmDialog.vue';
</script>
