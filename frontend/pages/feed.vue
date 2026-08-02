<script setup lang="ts">
const api = useApi()
const { smart } = useTime()
const PAGE_SIZE = 30

interface FeedItem {
  id: number
  type: number
  time: string
  content_md: string
  merged_suffix_md: string | null
  merged_from_id: number | null
  merged_link_md?: string[]
  user: { uid: number; name: string; color: string; badge: string | null; avatar: string | null } | null
}

// 首屏不等待后端：先显示页面，再拉第一页犇犇。
const { data: firstPage, pending: firstPending } = useLazyAsyncData('feed-first', () =>
  api<FeedItem[]>('/feed', { query: { limit: PAGE_SIZE } }),
  { server: false },
)

const items = ref<FeedItem[]>([])
const loading = ref(false)
const beforeTs = ref<string | null>(null)
const noMore = ref(false)

// 第一页回来后再填充列表，避免页面导航被接口阻塞。
watch(firstPage, (page) => {
  if (!page) return
  items.value = [...page]
  beforeTs.value = page.length ? page[page.length - 1].time : null
  noMore.value = page.length === 0
}, { immediate: true })

async function loadMore() {
  if (loading.value || noMore.value) return
  loading.value = true
  try {
    const q: Record<string, any> = { limit: PAGE_SIZE }
    if (beforeTs.value) q.before = beforeTs.value
    const page = await api<FeedItem[]>('/feed', { query: q })
    items.value.push(...page)
    if (page.length === 0) {
      noMore.value = true
    } else {
      beforeTs.value = page[page.length - 1].time
    }
  } finally {
    loading.value = false
  }
}

const { render } = useMarkdown()
function markMergedLinks(html: string, links: string[]) {
  let marked = html
  for (const link of links) {
    const anchor = render(link).match(/<a\b[^>]*>[\s\S]*?<\/a>/i)?.[0]
    if (!anchor || !marked.includes(anchor)) continue
    marked = marked.replace(
      anchor,
      `<span class="feed-auto-merged-link">${anchor}</span>`,
    )
  }
  return marked
}

function feedHtml(content: string, mergedSuffix: string | null, mergedLinks: string[]) {
  let html = mergedSuffix
    ? (() => {
        const prefix = content.slice(0, Math.max(0, content.length - mergedSuffix.length))
        return render(prefix)
          + `<div class="feed-auto-merged" aria-label="系统补全内容">${render(mergedSuffix)}</div>`
      })()
    : render(content)
  if (mergedLinks.length) html = markMergedLinks(html, mergedLinks)
  return html
}

const listRef = ref<HTMLElement | null>(null)
useCopyCode(listRef)
</script>

<template>
  <div>
    <section class="feed-hero">
      <h1>伪全网犇</h1>
      <p>这里汇总本站爬到的所有用户的犇犇，按时间倒序。</p>
    </section>

    <LoadingPanel v-if="firstPending && !items.length" title="正在加载犇犇" text="页面已经打开，正在读取最新的“洛谷微博”…" />

    <ul v-else ref="listRef" class="feed-list">
      <li v-for="f in items" :key="f.id" class="feed-item">
        <NuxtLink v-if="f.user" :to="`/user/${f.user.uid}`" class="avatar-link">
          <img
            v-if="f.user.avatar"
            :src="f.user.avatar"
            alt=""
            class="avatar"
            loading="lazy"
          >
          <div
            v-else
            class="avatar avatar-fallback"
            :data-color="f.user.color"
          >{{ (f.user.name || '?').charAt(0).toUpperCase() }}</div>
        </NuxtLink>
        <div v-else class="avatar avatar-fallback" data-color="Gray">?</div>

        <div class="body">
          <header class="meta">
            <LuoguUserName :user="f.user" show-badge />
            <span class="time">{{ smart(f.time) }}</span>
          </header>
          <div class="lg-content content" v-html="feedHtml(f.content_md, f.merged_suffix_md, f.merged_link_md || [])" />
          <footer class="feed-foot">
            <span class="feed-id">#{{ f.id }}</span>
            <FeedReplyButton :content="f.content_md" :sender-name="f.user?.name" />
          </footer>
        </div>
      </li>
    </ul>

    <div class="loader">
      <button v-if="!noMore" :disabled="loading" @click="loadMore">
        {{ loading ? '加载中...' : '加载更多' }}
      </button>
      <span v-else class="empty">没有更多了</span>
    </div>
  </div>
</template>

<style scoped>
.feed-hero {
  position: relative;
  border-radius: 12px;
  padding: 24px 28px;
  margin-bottom: 20px;
  overflow: hidden;
  background: var(--hero-bg);
  border: 1px solid var(--hero-border);
}
.feed-hero h1 {
  margin: 0;
  color: var(--hero-text);
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: 0.3px;
}
.feed-hero p {
  margin: 8px 0 0;
  color: var(--hero-text-muted);
  font-size: 14px;
}
.note {
  color: var(--text-muted);
}
.feed-list {
  list-style: none;
  padding: 0;
}

/* 单条犇犇：左头像 + 右内容（上：用户名 + 时间；下：正文） */
.feed-item {
  display: flex;
  gap: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 10px;
}

.avatar-link {
  flex-shrink: 0;
  text-decoration: none;
}
.avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--bg);
  display: block;
}
.avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
  font-weight: 600;
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

.body {
  flex: 1;
  min-width: 0;
  /* 防止内部连续长字符串撑爆容器，强制按需断行 */
  overflow-wrap: anywhere;
  word-break: break-word;
}
.meta {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.meta > * {
  /* 让 LuoguUserName / 时间等子项也允许收缩、换行 */
  min-width: 0;
}
.time {
  color: var(--text-muted);
  font-size: 12px;
}
.content {
  font-size: 15px;
  line-height: 1.65;
  /* anywhere 比 break-word 更激进，能拆超长无空格 token（URL、ID 串） */
  overflow-wrap: anywhere;
  word-break: break-word;
}
.content :deep(img) {
  max-width: 100%;
  height: auto;
}

/* 自动补回的回复后缀保留原 Markdown，同时用下划线提示来源。 */
.content :deep(.feed-auto-merged) {
  text-decoration-line: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.content :deep(.feed-auto-merged img) {
  box-shadow: 0 2px 0 currentColor;
}
.content :deep(.feed-auto-merged-link),
.content :deep(.feed-auto-merged-link a) {
  text-decoration-line: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.feed-foot {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.feed-id {
  font-size: 11px;
  color: var(--text-muted);
  font-family: ui-monospace, "SF Mono", Consolas, monospace;
  opacity: 0.55;
}

.loader {
  text-align: center;
  padding: 20px;
}
.loader button {
  padding: 8px 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  color: var(--text);
}
.loader .empty {
  color: var(--text-muted);
}

@media (max-width: 768px) {
  .feed-hero {
    padding: 20px 18px;
  }
}
</style>
