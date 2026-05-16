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
      <li v-for="f in items" :key="f.id">
        <div class="head">
          <LuoguUserName :user="f.user" show-badge />
          <span class="time">{{ smart(f.time) }}</span>
        </div>
        <div class="lg-content" v-html="feedHtml(f.content_md)" />
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
.feed-list li {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 8px;
}
.head {
  display: flex;
  justify-content: space-between;
  color: var(--text-muted);
  font-size: 14px;
  margin-bottom: 6px;
}
.time {
  color: var(--text-muted);
  font-size: 13px;
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
