<script setup lang="ts">
const { format } = useTime()

const route = useRoute()
const api = useApi()
const id = route.params.id as string

interface ArticleDetail {
  article_id: string
  title: string
  content_md: string
  admin_note: string | null
  author: any
  crawled_at: string
  version_count: number
}

// 不阻塞页面首屏：先渲染页面骨架，再由浏览器请求后端接口。
const { data, error, pending } = useLazyAsyncData(`article-${id}`, () =>
  api<ArticleDetail>(`/article/${id}`),
  { server: false },
)

const { render } = useMarkdown()
const html = computed(() => (data.value ? render(data.value.content_md) : ''))
const adminNoteHtml = computed(() =>
  data.value?.admin_note ? render(data.value.admin_note) : '',
)

const contentRef = ref<HTMLElement | null>(null)
useCopyCode(contentRef)

const copiedOriginal = ref(false)
const crawledAtText = computed(() =>
  data.value ? format(data.value.crawled_at) : '',
)

async function copyOriginalMarkdown() {
  if (!data.value?.content_md) return
  await navigator.clipboard.writeText(data.value.content_md)
  copiedOriginal.value = true
  setTimeout(() => { copiedOriginal.value = false }, 1400)
}
</script>

<template>
  <LoadingPanel v-if="pending" title="正在加载文章" text="页面已经打开，正在读取这篇文章的归档内容…" />

  <div v-else-if="error" class="error-box">
    <h2>{{ error.data?.message || '加载失败' }}</h2>
    <p v-if="error.statusCode === 404">
      如果本站从未爬取过这篇文章，刚才已触发一次爬取，稍等片刻刷新即可。
    </p>
  </div>

  <div v-else-if="data" class="article-wrap">
    <!-- 顶部 Banner：背景色块 + 标题 + 作者行 -->
    <header class="article-banner">
      <h1 class="article-title">{{ data.title }}</h1>
      <div class="article-meta">
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
          <a
            :href="`https://www.luogu.com.cn/article/${id}`"
            target="_blank"
            rel="noopener noreferrer"
            class="meta-action-btn"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M14 4h6v6M10 14L20 4M20 14v6H4V4h6"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span>查看原文</span>
          </a>
          <button type="button" class="meta-copy-btn" @click="copyOriginalMarkdown">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M8 8h10v12H8zM6 16H4V4h12v2"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linejoin="round"
              />
            </svg>
            <span>{{ copiedOriginal ? '已复制' : '复制原文' }}</span>
          </button>
          <span class="meta-item">上次更新 · {{ crawledAtText }}</span>
          <NuxtLink
            v-if="data.version_count > 1"
            :to="`/article/${id}/history`"
            class="meta-item link"
          >{{ data.version_count }} 个历史版本</NuxtLink>
          <SaveButton content-type="article" :content-id="id" />
        </div>
      </div>
    </header>

    <!-- 与洛谷文章页保持一致：红色引用块 + 固定的“管理组提示：”标题。 -->
    <blockquote v-if="data.admin_note" class="admin-public-comment">
      <p class="admin-public-comment-title">管理组提示：</p>
      <div class="lg-content admin-public-comment-content" v-html="adminNoteHtml" />
    </blockquote>

    <article ref="contentRef" class="lg-content" v-html="html" />
  </div>
</template>

<style scoped>
.article-wrap {
  width: 100%;
  max-width: none;
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

/* 蓝色渐变标题头 */
.article-banner {
  position: relative;
  overflow: hidden;
  background: var(--hero-bg);
  border: 1px solid var(--hero-border);
  border-radius: 12px;
  padding: 22px 26px 18px;
  margin-bottom: 16px;
}
.dark .article-banner {
  background: var(--hero-bg);
  border-color: var(--hero-border);
}

.article-title {
  position: relative;
  z-index: 1;
  margin: 0 0 14px;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.35;
  color: var(--text);
}

.article-meta {
  position: relative;
  z-index: 1;
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
.meta-item.link { color: var(--link); text-decoration: none; }
.meta-item.link:hover { text-decoration: underline; }
.meta-action-btn,
.meta-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--hero-border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  transition: border-color 0.15s, color 0.15s, transform 0.1s;
}
.meta-action-btn {
  text-decoration: none;
}
.meta-action-btn:hover,
.meta-copy-btn:hover {
  border-color: var(--link);
  color: var(--link);
  transform: translateY(-1px);
  text-decoration: none;
}
.meta-action-btn svg,
.meta-copy-btn svg {
  width: 15px;
  height: 15px;
  flex: 0 0 auto;
}

/* 复刻洛谷文章页的管理员公开提示样式。 */
.admin-public-comment {
  margin: 0 0 20px;
  padding: 10px 20px;
  background: color-mix(in srgb, var(--lg-red) 12%, var(--surface));
  border: 0;
  border-left: 5px solid var(--lg-red);
  color: var(--text);
  white-space: pre-wrap;
}
.admin-public-comment-title {
  margin: 0 0 0.3em;
  font-weight: 700;
}
.admin-public-comment-content {
  color: inherit;
}
.admin-public-comment-content :deep(> :first-child) {
  margin-top: 0;
}
.admin-public-comment-content :deep(> :last-child) {
  margin-bottom: 0;
}

.error-box {
  padding: 30px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  text-align: center;
}

@media (max-width: 640px) {
  .article-banner { padding: 18px 16px 14px; }
  .article-title { font-size: 21px; }
  .meta-right { margin-left: 0; }
}
</style>
