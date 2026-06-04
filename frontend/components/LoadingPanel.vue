<script setup lang="ts">
// 通用加载窗口：所有页面统一显示极简提示，避免文案扰乱界面。
defineProps<{
  title?: string
  text?: string
}>()
</script>

<template>
  <div class="loading-panel" role="status" aria-live="polite">
    <div class="loading-card">
      <div class="spinner" aria-hidden="true" />
      <div class="loading-title">loading……</div>
    </div>
  </div>
</template>

<style scoped>
.loading-panel {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  box-sizing: border-box;
}

.loading-card {
  display: flex;
  align-items: center;
  gap: 16px;
  width: min(100%, 520px);
  padding: 22px 24px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
}

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid color-mix(in srgb, var(--link) 20%, transparent);
  border-top-color: var(--link);
  border-radius: 50%;
  flex: 0 0 auto;
  animation: spin 0.9s linear infinite;
}

.loading-title {
  font-weight: 700;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
