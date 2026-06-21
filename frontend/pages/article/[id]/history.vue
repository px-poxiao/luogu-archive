<script setup lang="ts">
const route = useRoute()
const id = route.params.id as string
const api = useApi()

interface VersionEntry {
  id: number
  title: string | null
  content_md: string
  content_hash: string
  crawled_at: string
  is_current: boolean
}

interface ArticleHistoryResp {
  article_id: string
  title: string
  versions: VersionEntry[]
}

const { data, error, pending } = useLazyAsyncData(`article-history-${id}`, () =>
  api<ArticleHistoryResp>(`/article/${id}/history`),
  { server: false },
)
</script>

<template>
  <LoadingPanel v-if="pending" title="正在加载历史版本" text="正在读取这篇文章的历史版本…" />

  <div v-else-if="error" class="error-box">
    <h2>{{ error.data?.message || '加载失败' }}</h2>
  </div>

  <div v-else-if="data" class="history-page">
    <PageHero
      :title="data.title"
      subtitle="文章历史版本"
    >
      <template #extra>
        <NuxtLink :to="`/article/${id}`" class="hero-link">返回文章</NuxtLink>
      </template>
    </PageHero>

    <VersionHistoryTimeline :versions="data.versions" empty-text="暂无文章历史版本" />
  </div>
</template>

<style scoped>
.history-page {
  display: grid;
  gap: 18px;
}

.hero-link {
  display: inline-flex;
  margin-top: 12px;
  color: var(--link);
  font-size: 14px;
}

.error-box {
  padding: 30px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  text-align: center;
}
</style>
