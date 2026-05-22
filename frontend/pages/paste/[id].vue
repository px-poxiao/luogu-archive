<script setup lang="ts">
const { format } = useTime()

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

const contentRef = ref<HTMLElement | null>(null)
useCopyCode(contentRef)

const crawledAtText = computed(() =>
  data.value ? format(data.value.crawled_at) : '',
)
</script>

<template>
  <div v-if="error" class="error-box">
    <h2>{{ error.data?.message || '加载失败' }}</h2>
    <p v-if="error.statusCode === 404">
      刚才已触发一次爬取，稍等片刻刷新即可。
    </p>
  </div>

  <div v-else-if="data" class="paste-wrap">
    <!-- 顶部 Banner：背景色块 + 标题 + 作者行 -->
    <header class="paste-banner">
      <h1 class="paste-title">剪贴板 {{ id }}</h1>
      <div class="paste-meta">
        <div class="author-block">
          <NuxtLink
            v-if="data.author"
            :to="`/user/${data.author.uid}`"
            class="author-link"
          >
            <img
              v-if="data.author.avatar"
              :src="data.author.avatar"
              alt=""
              class="author-avatar"
              loading="lazy"
            >
            <div
              v-else
              class="author-avatar avatar-fallback"
              :data-color="data.author.color"
            >{{ (data.author.name || '?').charAt(0).toUpperCase() }}</div>
            <LuoguUserName :user="data.author" show-badge no-link />
          </NuxtLink>
          <span v-else class="author-link">作者未收录</span>
        </div>

        <div class="meta-right">
          <span class="meta-item">上次更新 · {{ crawledAtText }}</span>
          <NuxtLink
            v-if="data.version_count > 1"
            :to="`/paste/${id}/history`"
            class="meta-item link"
          >{{ data.version_count }} 个历史版本</NuxtLink>
        </div>
      </div>
    </header>

    <OriginBanner
      :origin-url="`https://www.luogu.com.cn/paste/${id}`"
      :author-name="data.author?.name"
      :author-href="data.author ? `/user/${data.author.uid}` : undefined"
      :crawled-at="data.crawled_at"
      content-type="paste"
      :content-id="id"
    />

    <article ref="contentRef" class="lg-content" v-html="html" />
  </div>
</template>

<style scoped>
.paste-wrap {
  max-width: 860px;
  margin: 0 auto;
  padding: 0 8px;
}

.paste-banner {
  background: var(--article-banner-bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 28px 32px 20px;
  margin-bottom: 16px;
}

.paste-title {
  margin: 0 0 14px;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.35;
  color: var(--text);
}

.paste-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px 20px;
  font-size: 14px;
  color: var(--text-muted);
}

.author-block { display: flex; align-items: center; }
.author-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  color: inherit;
}
.author-link:hover { text-decoration: none; }
.author-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg);
  flex-shrink: 0;
}
.avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 600;
  font-size: 14px;
  background: var(--lg-gray);
}
.avatar-fallback[data-color="Blue"]    { background: var(--lg-blue); }
.avatar-fallback[data-color="Green"]   { background: var(--lg-green); }
.avatar-fallback[data-color="Orange"]  { background: var(--lg-orange); }
.avatar-fallback[data-color="Red"]     { background: var(--lg-red); }
.avatar-fallback[data-color="Purple"]  { background: var(--lg-purple); }
.avatar-fallback[data-color="Cyan"]    { background: var(--lg-cyan); }
.avatar-fallback[data-color="Black"]   { background: var(--lg-black); }
.avatar-fallback[data-color="Cheater"] { background: var(--lg-cheater-tag); }

.meta-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.meta-item { font-size: 13px; }
.meta-item.link { color: var(--link); }

.error-box {
  padding: 30px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  text-align: center;
}

@media (max-width: 640px) {
  .paste-banner { padding: 20px 18px 16px; }
  .paste-title { font-size: 22px; }
  .meta-right { margin-left: 0; }
}
</style>
