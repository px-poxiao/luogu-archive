<script setup lang="ts">
const route = useRoute()
const api = useApi()
const { format } = useTime()
const { render } = useMarkdown()
const id = Number(route.params.id)
const perPage = 30
const currentPage = computed(() => Math.max(1, Number.parseInt(String(route.query.page || '1'), 10) || 1))

interface UserBrief {
  uid: number
  name: string
  color: string
  badge: string | null
  avatar: string | null
  ccf_level: number
  xcpc_level: number
  is_admin: boolean
}

interface DiscussionReply {
  reply_id: number
  content_md: string
  author: UserBrief | null
  source_time: string | null
  crawled_at: string
}

interface DiscussionDetail {
  discussion_id: number
  title: string
  content_md: string
  author: UserBrief | null
  forum_name: string | null
  source_time: string | null
  crawled_at: string
  source_reply_count: number
  stored_reply_count: number
  page: number
  per_page: number
  replies: DiscussionReply[]
}

const { data, error, pending } = useLazyAsyncData(
  `discussion-${id}`,
  () => api<DiscussionDetail>(`/discuss/${id}`, {
    query: { page: currentPage.value, per_page: perPage },
  }),
  { server: false, watch: [currentPage] },
)

const totalPages = computed(() => Math.max(1, Math.ceil((data.value?.stored_reply_count || 0) / perPage)))
const contentRef = ref<HTMLElement | null>(null)
useCopyCode(contentRef)
const copied = ref<string | null>(null)

async function copyMarkdown(key: string, content: string) {
  await navigator.clipboard.writeText(content)
  copied.value = key
  setTimeout(() => {
    if (copied.value === key) copied.value = null
  }, 1400)
}

function goPage(page: number) {
  if (page < 1 || page > totalPages.value || page === currentPage.value) return
  navigateTo({ path: route.path, query: page === 1 ? {} : { page } })
}
</script>

<template>
  <LoadingPanel v-if="pending && !data" title="正在加载讨论" text="正在读取主帖和已归档回复…" />

  <div v-else-if="error && !data" class="error-box">
    <h2>{{ error.data?.message || '加载失败' }}</h2>
    <p v-if="error.statusCode === 404">首次保存已经进入队列，稍后刷新即可查看。</p>
  </div>

  <div v-else-if="data" ref="contentRef" class="discussion-page">
    <header class="discussion-head">
      <div class="head-main">
        <span v-if="data.forum_name" class="forum-name">{{ data.forum_name }}</span>
        <h1>{{ data.title }}</h1>
        <div class="author-row">
          <NuxtLink v-if="data.author" :to="`/user/${data.author.uid}`" class="author-link">
            <img v-if="data.author.avatar" :src="data.author.avatar" alt="" class="avatar">
            <LuoguUserName :user="data.author" show-badge no-link />
          </NuxtLink>
          <span v-else>发帖人未收录</span>
          <time v-if="data.source_time" :datetime="data.source_time">{{ format(data.source_time) }}</time>
        </div>
      </div>
      <div class="head-actions">
        <a :href="`https://www.luogu.com.cn/discuss/${id}`" target="_blank" rel="noopener noreferrer" class="archive-action-button">
          查看原文
        </a>
        <button type="button" class="archive-action-button" @click="copyMarkdown('post', data.content_md)">
          {{ copied === 'post' ? '已复制' : '复制原文' }}
        </button>
        <SaveButton content-type="discuss" :content-id="String(id)" />
      </div>
    </header>

    <article class="post-body lg-content" v-html="render(data.content_md)" />

    <section class="reply-section" aria-labelledby="reply-title">
      <header class="reply-head">
        <div>
          <h2 id="reply-title">回复</h2>
          <p>本站已归档 {{ data.stored_reply_count }} 条，源站记录 {{ data.source_reply_count }} 条。</p>
        </div>
        <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
      </header>

      <div v-if="data.replies.length" class="reply-list">
        <article
          v-for="reply in data.replies"
          :id="`reply-${reply.reply_id}`"
          :key="reply.reply_id"
          class="reply-item"
        >
          <header class="reply-meta">
            <NuxtLink v-if="reply.author" :to="`/user/${reply.author.uid}`" class="author-link">
              <img v-if="reply.author.avatar" :src="reply.author.avatar" alt="" class="avatar small">
              <LuoguUserName :user="reply.author" show-badge no-link />
            </NuxtLink>
            <span v-else>用户未收录</span>
            <time v-if="reply.source_time" :datetime="reply.source_time">{{ format(reply.source_time) }}</time>
            <span class="reply-id">#{{ reply.reply_id }}</span>
            <button
              type="button"
              class="copy-reply"
              @click="copyMarkdown(`reply-${reply.reply_id}`, reply.content_md)"
            >{{ copied === `reply-${reply.reply_id}` ? '已复制' : '复制原文' }}</button>
          </header>
          <div class="lg-content reply-body" v-html="render(reply.content_md)" />
        </article>
      </div>
      <p v-else class="empty-replies">本页没有已归档回复。</p>

      <nav v-if="totalPages > 1" class="pagination" aria-label="回复分页">
        <button type="button" :disabled="currentPage <= 1" title="上一页" @click="goPage(currentPage - 1)">‹</button>
        <span>{{ currentPage }} / {{ totalPages }}</span>
        <button type="button" :disabled="currentPage >= totalPages" title="下一页" @click="goPage(currentPage + 1)">›</button>
      </nav>
    </section>
  </div>
</template>

<style scoped>
.discussion-page { display: grid; gap: 18px; }
.discussion-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 22px;
  padding: 22px 26px;
  border: 1px solid var(--hero-border);
  border-radius: 8px;
  background: var(--hero-bg);
}
.head-main { min-width: 0; }
.forum-name { color: var(--link); font-size: 13px; font-weight: 650; }
.discussion-head h1 { margin: 5px 0 13px; font-size: 25px; line-height: 1.35; }
.author-row, .author-link, .head-actions, .reply-meta, .pagination {
  display: flex;
  align-items: center;
}
.author-row { gap: 14px; color: var(--text-muted); font-size: 13px; }
.author-link { gap: 8px; color: inherit; text-decoration: none; }
.avatar { width: 32px; height: 32px; border-radius: 50%; object-fit: cover; }
.avatar.small { width: 27px; height: 27px; }
.head-actions { justify-content: flex-end; gap: 9px; flex-wrap: wrap; }
.copy-reply, .pagination button {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font: inherit;
}
.copy-reply:hover, .pagination button:hover:not(:disabled) { border-color: var(--link); color: var(--link); }
.post-body { padding: 26px; border-bottom: 1px solid var(--border); }
.reply-section { display: grid; gap: 14px; }
.reply-head { display: flex; justify-content: space-between; align-items: end; gap: 18px; }
.reply-head h2 { margin: 0; font-size: 20px; }
.reply-head p { margin: 5px 0 0; color: var(--text-muted); font-size: 13px; }
.reply-head > span { color: var(--text-muted); font-size: 13px; }
.reply-list { display: grid; gap: 10px; }
.reply-item { border: 1px solid var(--border); border-radius: 8px; background: var(--surface); overflow: hidden; }
.reply-meta { min-height: 46px; gap: 12px; padding: 7px 14px; border-bottom: 1px solid var(--border); color: var(--text-muted); font-size: 12px; }
.reply-id { margin-left: auto; }
.copy-reply { padding: 4px 8px; font-size: 12px; }
.reply-body { padding: 16px 18px; }
.reply-body :deep(> :first-child), .post-body :deep(> :first-child) { margin-top: 0; }
.reply-body :deep(> :last-child), .post-body :deep(> :last-child) { margin-bottom: 0; }
.empty-replies, .error-box { padding: 30px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); text-align: center; }
.pagination { justify-content: center; gap: 14px; }
.pagination button { width: 36px; height: 34px; font-size: 24px; line-height: 1; }
.pagination button:disabled { opacity: 0.4; cursor: default; }
.pagination span { min-width: 76px; text-align: center; color: var(--text-muted); font-size: 13px; }
@media (max-width: 720px) {
  .discussion-head { display: grid; padding: 18px 16px; }
  .head-actions { justify-content: flex-start; }
  .discussion-head h1 { font-size: 21px; }
  .post-body { padding: 18px 4px; }
  .reply-meta { flex-wrap: wrap; }
  .reply-id { margin-left: 0; }
  .copy-reply { margin-left: auto; }
}
</style>
