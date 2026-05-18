<script setup lang="ts">
const api = useApi()
const { smart } = useTime()

interface FeedItem {
  id: number
  type: number
  time: string
  content_md: string
  user: { uid: number; name: string; color: string; badge: string | null; avatar: string | null } | null
}

const items = ref<FeedItem[]>([])
const loading = ref(false)
const beforeTs = ref<string | null>(null)
const noMore = ref(false)

async function loadMore() {
  if (loading.value || noMore.value) return
  loading.value = true
  try {
    const q: Record<string, any> = { limit: 30 }
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
function feedHtml(c: string) { return render(c) }

const listRef = ref<HTMLElement | null>(null)
useCopyCode(listRef)

onMounted(() => loadMore())
</script>

<template>
  <div>
    <h1>伪全网犇</h1>
    <p class="note">这里汇总本站爬到的所有用户的犇犇，按时间倒序。</p>

    <ul ref="listRef" class="feed-list">
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
          <div class="lg-content content" v-html="feedHtml(f.content_md)" />
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
.avatar-fallback[data-color="Cheater"] { background: var(--lg-cheater); }

.body {
  flex: 1;
  min-width: 0;
}
.meta {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.time {
  color: var(--text-muted);
  font-size: 12px;
}
.content {
  font-size: 15px;
  line-height: 1.65;
  word-wrap: break-word;
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
</style>
