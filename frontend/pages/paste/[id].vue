<script setup lang="ts">
const route = useRoute()
const api = useApi()
const id = route.params.id as string

interface PasteDetail {
  paste_id: string
  content_md: string
  author: any
  crawled_at: string
  version_count: number
}

const { data, error } = await useAsyncData(`paste-${id}`, () =>
  api<PasteDetail>(`/paste/${id}`),
)

const { render } = useMarkdown()
const html = computed(() => (data.value ? render(data.value.content_md) : ''))
</script>

<template>
  <div v-if="error" class="error-box">
    <h2>{{ error.data?.message || '加载失败' }}</h2>
    <p v-if="error.statusCode === 404">
      刚才已触发一次爬取，稍等片刻刷新即可。
    </p>
  </div>

  <div v-else-if="data">
    <OriginBanner
      :origin-url="`https://www.luogu.com.cn/paste/${id}`"
      :author-name="data.author?.name"
      :author-href="data.author ? `/user/${data.author.uid}` : undefined"
      :crawled-at="data.crawled_at"
      content-type="paste"
      :content-id="id"
    />

    <h1>剪贴板 {{ id }}</h1>
    <div class="meta">
      <LuoguUserName v-if="data.author" :user="data.author" show-badge />
    </div>

    <article class="lg-content" v-html="html" />
  </div>
</template>

<style scoped>
.meta {
  color: var(--text-muted);
  margin-bottom: 20px;
}
.error-box {
  padding: 30px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  text-align: center;
}
</style>
