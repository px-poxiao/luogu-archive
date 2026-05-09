<script setup lang="ts">
const route = useRoute()
const api = useApi()
const id = route.params.id as string

interface ArticleDetail {
  article_id: string
  title: string
  content_md: string
  author: any
  crawled_at: string
  version_count: number
}

const { data, error } = await useAsyncData(`article-${id}`, () =>
  api<ArticleDetail>(`/article/${id}`),
)

const { render } = useMarkdown()
const html = computed(() => (data.value ? render(data.value.content_md) : ''))
</script>

<template>
  <div v-if="error" class="error-box">
    <h2>{{ error.data?.message || '加载失败' }}</h2>
    <p v-if="error.statusCode === 404">
      如果本站从未爬取过这篇文章，刚才已触发一次爬取，稍等片刻刷新即可。
    </p>
  </div>

  <div v-else-if="data">
    <OriginBanner
      :origin-url="`https://www.luogu.com.cn/article/${id}`"
      :author-name="data.author?.name"
      :author-href="data.author ? `/user/${data.author.uid}` : undefined"
      :crawled-at="data.crawled_at"
      content-type="article"
      :content-id="id"
    />

    <h1>{{ data.title }}</h1>

    <div class="meta">
      <LuoguUserName v-if="data.author" :user="data.author" show-badge />
      <span v-if="data.version_count > 1">
        · <NuxtLink :to="`/article/${id}/history`">{{ data.version_count }} 个历史版本</NuxtLink>
      </span>
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
