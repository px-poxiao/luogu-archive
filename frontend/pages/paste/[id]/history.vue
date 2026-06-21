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

interface PasteHistoryResp {
  paste_id: string
  versions: VersionEntry[]
}

const { data, error, pending } = useLazyAsyncData(`paste-history-${id}`, () =>
  api<PasteHistoryResp>(`/paste/${id}/history`),
  { server: false },
)
</script>

<template>
  <LoadingPanel v-if="pending" title="正在加载历史版本" text="正在读取这个剪贴板的历史版本…" />

  <div v-else-if="error" class="error-box">
    <h2>{{ error.data?.message || '加载失败' }}</h2>
  </div>

  <div v-else-if="data" class="history-page">
    <PageHero
      :title="`剪贴板 ${id}`"
      subtitle="剪贴板历史版本"
    >
      <template #extra>
        <NuxtLink :to="`/paste/${id}`" class="hero-link">返回剪贴板</NuxtLink>
      </template>
    </PageHero>

    <VersionHistoryTimeline :versions="data.versions" empty-text="暂无剪贴板历史版本" />
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
