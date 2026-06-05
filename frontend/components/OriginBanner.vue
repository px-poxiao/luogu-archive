<!--
  蓝色渐变页面头图 + 原文归属 + 保存按钮。
  内容详情页（文章 / 剪贴板 / 用户 / 陶片 / 题目）顶部挂一个。
-->
<script setup lang="ts">
const { fromNow } = useTime()

const props = defineProps<{
  originUrl: string
  title?: string
  compact?: boolean
  authorName?: string
  authorHref?: string
  crawledAt?: string | Date
  contentType: string
  contentId: string
}>()

const relTime = computed(() =>
  props.crawledAt ? fromNow(props.crawledAt) : '未知',
)
</script>

<template>
  <div class="origin-hero" :class="{ compact }">
    <div class="hero-inner">
      <h1 v-if="title" class="hero-title">{{ title }}</h1>
      <div class="hero-meta">
        <span class="attr">
          <a :href="originUrl" target="_blank" rel="noopener noreferrer">查看洛谷原文</a>
          <span v-if="authorName">
            · 作者：
            <a v-if="authorHref" :href="authorHref">{{ authorName }}</a>
            <span v-else>{{ authorName }}</span>
          </span>
          · 上次更新：{{ relTime }}
        </span>
        <SaveButton :content-type="contentType" :content-id="contentId" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.origin-hero {
  position: relative;
  border-radius: 12px;
  padding: 22px 26px;
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
  margin: 0 0 10px;
  color: var(--hero-text);
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 0.3px;
}
.hero-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.attr {
  flex: 1;
  min-width: 0;
  color: var(--hero-text-muted);
  font-size: 13.5px;
}
.attr a {
  color: var(--link);
  text-decoration: none;
}
.attr a:hover { text-decoration: underline; }

@media (max-width: 768px) {
  .origin-hero { padding: 18px 16px; border-radius: 12px; }
  .hero-title { font-size: 21px; }
}

.origin-hero.compact {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 16px;
}
.origin-hero.compact .hero-title { display: none; }
</style>
