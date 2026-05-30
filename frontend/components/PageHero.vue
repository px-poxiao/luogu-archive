<script setup lang="ts">
// 蓝色渐变页面头图。用于没有 OriginBanner 的用户端页面（feed / judgement / me / takedown / 登录注册等）。
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <div class="page-hero">
    <div class="hero-inner">
      <h1 class="hero-title">{{ title }}</h1>
      <p v-if="subtitle" class="hero-sub">{{ subtitle }}</p>
      <slot name="extra" />
    </div>
  </div>
</template>

<style scoped>
.page-hero {
  position: relative;
  border-radius: 12px;
  padding: 24px 28px;
  margin-bottom: 20px;
  overflow: hidden;
  background: var(--hero-bg);
  border: 1px solid var(--hero-border);
}
.hero-inner {
  position: relative;
  z-index: 1;
}
.hero-title {
  margin: 0;
  color: var(--hero-text);
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 0.3px;
}
.hero-sub {
  margin: 8px 0 0;
  color: var(--hero-text-muted);
  font-size: 14px;
}
:deep(.hero-sub a) {
  color: var(--link);
}

@media (max-width: 768px) {
  .page-hero { padding: 20px 18px; border-radius: 12px; }
  .hero-title { font-size: 21px; }
}
</style>
