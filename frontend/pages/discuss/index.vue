<script setup lang="ts">
const api = useApi()
const { format } = useTime()
const page = ref(1)
const selectedForum = ref('')
const pageSize = 30

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

interface ForumItem {
  name: string
  slug: string
  count: number
}

interface DiscussionItem {
  discussion_id: number
  title: string
  author: UserBrief | null
  forum_name: string | null
  source_time: string | null
  crawled_at: string
  stored_reply_count: number
  latest_reply_author: UserBrief | null
  latest_reply_time: string | null
}

interface DiscussionListResponse {
  items: DiscussionItem[]
  forums: ForumItem[]
  total: number
  page: number
  page_size: number
}

const { data, pending } = useLazyAsyncData(
  'discussion-list',
  () => api<DiscussionListResponse>('/discuss', {
    query: {
      page: page.value,
      page_size: pageSize,
      forum: selectedForum.value || undefined,
    },
  }),
  { server: false, watch: [page, selectedForum] },
)

const totalPages = computed(() => Math.max(1, Math.ceil((data.value?.total || 0) / pageSize)))

function chooseForum(slug: string) {
  if (selectedForum.value === slug) return
  selectedForum.value = slug
  page.value = 1
}
</script>

<template>
  <div class="discussion-page">
    <aside class="forum-panel" aria-label="讨论版块">
      <h1>讨论区</h1>
      <button
        type="button"
        class="forum-option all"
        :class="{ active: !selectedForum }"
        @click="chooseForum('')"
      >
        <span class="forum-mark grid-mark" aria-hidden="true">▪</span>
        <span>全部版块</span>
      </button>
      <button
        v-for="forum in data?.forums || []"
        :key="forum.slug"
        type="button"
        class="forum-option"
        :class="[{ active: selectedForum === forum.slug }, `forum-${forum.slug}`]"
        @click="chooseForum(forum.slug)"
      >
        <span class="forum-mark" aria-hidden="true" />
        <span>{{ forum.name }}</span>
        <span class="forum-count">{{ forum.count }}</span>
      </button>
    </aside>

    <main class="discussion-main">
      <LoadingPanel v-if="pending && !data" title="正在读取讨论" text="正在加载已归档内容…" />

      <div v-else class="discussion-list">
        <NuxtLink
          v-for="item in data?.items || []"
          :key="item.discussion_id"
          :to="`/discuss/${item.discussion_id}`"
          class="discussion-card"
        >
          <div class="post-author">
            <img
              v-if="item.author?.avatar"
              :src="item.author.avatar"
              alt=""
              class="avatar"
            >
            <div v-else class="avatar avatar-fallback" aria-hidden="true">?</div>
          </div>

          <div class="post-main">
            <strong class="discussion-title">{{ item.title }}</strong>
            <div class="post-meta">
              <LuoguUserName v-if="item.author" :user="item.author" show-badge no-link />
              <span v-else class="muted">发帖人未收录</span>
              <time :datetime="item.source_time || item.crawled_at">
                {{ format(item.source_time || item.crawled_at) }}
              </time>
            </div>
          </div>

          <div class="post-status">
            <span class="forum-label">
              <i aria-hidden="true" />{{ item.forum_name || '未知版块' }}
            </span>
            <div class="reply-meta">
              <span class="reply-count">{{ item.stored_reply_count }} 条回复</span>
              <template v-if="item.latest_reply_author">
                <LuoguUserName :user="item.latest_reply_author" no-link />
                <time v-if="item.latest_reply_time" :datetime="item.latest_reply_time">
                  {{ format(item.latest_reply_time) }}
                </time>
              </template>
            </div>
          </div>
        </NuxtLink>

        <div v-if="!data?.items.length" class="empty">这个版块暂时没有已归档讨论</div>
      </div>

      <nav v-if="totalPages > 1" class="pagination" aria-label="讨论列表分页">
        <button class="archive-action-button" :disabled="page <= 1" @click="page--">上一页</button>
        <span>{{ page }} / {{ totalPages }}</span>
        <button class="archive-action-button" :disabled="page >= totalPages" @click="page++">下一页</button>
      </nav>
    </main>
  </div>
</template>

<style scoped>
.discussion-page {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  align-items: start;
  gap: 18px;
  max-width: 1180px;
  margin: 0 auto;
}
.forum-panel {
  position: sticky;
  top: 18px;
  display: grid;
  gap: 4px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}
.forum-panel h1 { margin: 0 0 9px; font-size: 19px; }
.forum-option {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 38px;
  padding: 7px 8px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font: inherit;
  text-align: left;
}
.forum-option:hover, .forum-option.active { background: var(--hover); }
.forum-mark { width: 8px; height: 8px; border-radius: 2px; background: var(--lg-orange); }
.grid-mark { width: auto; height: auto; background: none; color: var(--text-muted); font-size: 18px; line-height: 1; }
.forum-siteaffairs .forum-mark { background: var(--lg-blue); }
.forum-academics .forum-mark { background: #a855f7; }
.forum-service .forum-mark { background: var(--lg-green); }
.forum-count { color: var(--text-muted); font-size: 11px; }
.discussion-main { min-width: 0; }
.discussion-list { display: grid; gap: 10px; }
.discussion-card {
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr) minmax(220px, 32%);
  align-items: center;
  gap: 14px;
  min-height: 88px;
  padding: 14px 18px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  text-decoration: none;
  transition: border-color 0.15s, background 0.15s;
}
.discussion-card:hover { border-color: var(--link); background: color-mix(in srgb, var(--link) 3%, var(--surface)); }
.avatar { width: 46px; height: 46px; border-radius: 50%; object-fit: cover; }
.avatar-fallback { display: grid; place-items: center; background: var(--hover); color: var(--text-muted); font-weight: 700; }
.post-main, .post-status { min-width: 0; }
.discussion-title { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; }
.post-meta, .reply-meta, .forum-label { display: flex; align-items: center; }
.post-meta { gap: 9px; margin-top: 7px; color: var(--text-muted); font-size: 12px; }
.post-status { display: grid; justify-items: end; gap: 9px; }
.forum-label { gap: 6px; color: var(--text-muted); font-size: 12px; }
.forum-label i { width: 8px; height: 8px; border-radius: 2px; background: var(--lg-blue); }
.reply-meta { justify-content: flex-end; gap: 8px; min-width: 0; color: var(--text-muted); font-size: 12px; }
.reply-count { white-space: nowrap; }
.muted { color: var(--text-muted); }
.empty { padding: 48px 20px; border: 1px solid var(--border); background: var(--surface); color: var(--text-muted); text-align: center; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 14px; margin-top: 20px; }
@media (max-width: 820px) {
  .discussion-page { grid-template-columns: 1fr; }
  .forum-panel { position: static; display: flex; overflow-x: auto; padding: 10px; }
  .forum-panel h1 { display: none; }
  .forum-option { flex: 0 0 auto; width: auto; grid-template-columns: 8px auto; white-space: nowrap; }
  .forum-count { display: none; }
  .discussion-card { grid-template-columns: 40px minmax(0, 1fr); padding: 13px; }
  .avatar { width: 40px; height: 40px; }
  .post-status { grid-column: 2; justify-items: start; }
  .reply-meta { justify-content: flex-start; flex-wrap: wrap; }
}
</style>
