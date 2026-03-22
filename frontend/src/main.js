import { createApp } from 'vue';
import App from './App.vue';
import router from './router';
import { initRuntimeI18n } from './i18n/runtime';
import './styles.css';

const app = createApp(App);
app.use(router).mount('#app');
try {
  initRuntimeI18n();
} catch (error) {
  console.error('[runtime-i18n] init failed:', error);
}
