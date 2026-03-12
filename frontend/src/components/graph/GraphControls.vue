<template>
  <section class="panel controls-panel">
    <div class="panel-head">
      <h2>图谱控制</h2>
    </div>

    <div class="controls-body">
      <label class="field-label" for="depth-input">扩展深度</label>
      <input
        id="depth-input"
        class="number-input mono"
        type="number"
        min="1"
        max="4"
        :value="depth"
        @input="$emit('update-depth', Number($event.target.value) || 2)"
      />

      <button class="btn mono" type="button" @click="$emit('refresh-map')">刷新地图</button>
      <p class="hint muted">当前为骨架页面，后续接入真实图布局与筛选器。</p>
    </div>
  </section>
</template>

<script setup>
defineProps({
  depth: {
    type: Number,
    required: true
  }
});

defineEmits(['update-depth', 'refresh-map']);
</script>
