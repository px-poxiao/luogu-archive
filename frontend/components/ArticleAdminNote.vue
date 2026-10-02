<script setup lang="ts">
// 管理组提示独立于文章正文，普通文章页和插件原文使用同一套展示。
const props = defineProps<{ note?: string | null }>()
const { render } = useMarkdown()
const html = computed(() => props.note ? render(props.note) : '')
</script>

<template>
  <blockquote v-if="note" class="admin-public-comment">
    <p class="admin-public-comment-title">管理组提示：</p>
    <div class="lg-content admin-public-comment-content" v-html="html" />
  </blockquote>
</template>

<style scoped>
.admin-public-comment {
  margin: 0 0 20px;
  padding: 10px 20px;
  background: color-mix(in srgb, var(--lg-red) 12%, var(--surface));
  border: 0;
  border-left: 5px solid var(--lg-red);
  color: var(--text);
  overflow-wrap: anywhere;
}
.admin-public-comment-title { margin: 0 0 0.3em; font-weight: 700; }
.admin-public-comment-content { color: inherit; }
.admin-public-comment-content :deep(> :first-child) { margin-top: 0; }
.admin-public-comment-content :deep(> :last-child) { margin-bottom: 0; }
</style>
