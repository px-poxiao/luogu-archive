<script setup lang="ts">
const route = useRoute()
const api = useApi()
const { smart, format } = useTime()
const uid = route.params.uid as string

interface UserProfile {
  uid: number
  name: string
  avatar: string | null
  background: string | null
  slogan: string | null
  badge: string | null
  color: string
  is_admin: boolean
  is_banned: boolean
  ccf_level: number
  xcpc_level: number
  following_count: number
  follower_count: number
  ranking: number | null
  passed_problem_count: number | null
  submitted_problem_count: number | null
  register_time: string | null
  introduction_md: string | null
  last_crawled_at: string | null
  name_history: Array<{ name: string; first_seen_at: string; last_seen_at: string; is_hidden: boolean }>
  prizes: Array<{ year: number; contest: string; event: string | null; prize: string }>
  name_hidden: boolean
}

interface ActivityItem {
  kind: string
  time: string
  feed_id?: number
  feed_content?: string
  article_id?: string
  article_title?: string
  paste_id?: string
  judgement_reason?: string
}

const { data: profile, error } = await useAsyncData(`user-${uid}`, () =>
  api<UserProfile>(`/user/${uid}`),
)

const includeFeed = ref(true)
const { data: activity } = await useAsyncData(
  `user-activity-${uid}`,
  () =>
    api<ActivityItem[]>(`/user/${uid}/activity`, {
      query: { include_feed: includeFeed.value ? 'true' : 'false', limit: 50 },
    }),
  { watch: [includeFeed] },
)

const { render } = useMarkdown()
const introHtml = computed(() =>
  profile.value?.introduction_md ? render(profile.value.introduction_md) : '',
)
function feedHtml(c: string) { return render(c) }

const userBrief = computed(() => profile.value ? {
  uid: profile.value.uid,
  name: profile.value.name,
  color: profile.value.color,
  badge: profile.value.badge,
  avatar: profile.value.avatar,
} : null)

// 左侧 Tab 切换
type TabKey = 'activity' | 'intro' | 'prizes' | 'names'
const activeTab = ref<TabKey>('activity')

const tabs: Array<{ key: TabKey; label: string; show: () => boolean }> = [
  { key: 'activity', label: '活动', show: () => true },
  { key: 'intro', label: '个人介绍', show: () => !!profile.value?.introduction_md },
  { key: 'prizes', label: 'OI 获奖', show: () => (profile.value?.prizes?.length ?? 0) > 0 },
  { key: 'names', label: '用户名历史', show: () => (profile.value?.name_history?.length ?? 0) > 1 },
]

// 代码复制按钮：绑在右侧内容容器上，覆盖 activity / intro 两种 md 场景
const contentRef = ref<HTMLElement | null>(null)
useCopyCode(contentRef)
</script>

<template>
  <div v-if="error" class="error-box">
    <h2>{{ error.data?.message || '用户未收录' }}</h2>
    <p>已触发一次爬取，稍等片刻刷新即可。</p>
  </div>

  <div v-else-if="profile" class="user-page">
    <OriginBanner
      :origin-url="`https://www.luogu.com.cn/user/${uid}`"
      :crawled-at="profile.last_crawled_at"
      content-type="user"
      :content-id="String(uid)"
    />

    <div class="two-col">
      <!-- 左侧：用户信息 + Tab -->
      <aside class="sidebar">
        <section class="profile-head">
          <img v-if="profile.avatar" :src="profile.avatar" class="avatar" alt="">
          <h1 class="name-row">
            <LuoguUserName :user="userBrief" :hidden="profile.name_hidden" show-badge no-link />
          </h1>
          <p v-if="profile.slogan" class="slogan">{{ profile.slogan }}</p>

          <div class="badges">
            <span v-if="profile.is_banned" class="tag banned">已封禁</span>
            <span v-if="profile.is_admin" class="tag admin">管理员</span>
          </div>

          <FollowButton :uid="profile.uid" />

          <dl class="stats">
            <div><dt>关注</dt><dd>{{ profile.following_count }}</dd></div>
            <div><dt>粉丝</dt><dd>{{ profile.follower_count }}</dd></div>
            <div v-if="profile.ranking !== null"><dt>做题榜</dt><dd>#{{ profile.ranking }}</dd></div>
            <div v-if="profile.ccf_level > 0"><dt>CCF</dt><dd>{{ profile.ccf_level }}</dd></div>
            <div v-if="profile.xcpc_level > 0"><dt>XCPC</dt><dd>{{ profile.xcpc_level }}</dd></div>
          </dl>
        </section>

        <!-- Tab 切换（垂直方向，侧栏底部） -->
        <nav class="tabs">
          <button
            v-for="t in tabs.filter(x => x.show())"
            :key="t.key"
            :class="{ active: activeTab === t.key }"
            @click="activeTab = t.key"
          >{{ t.label }}</button>
        </nav>
      </aside>

      <!-- 右侧：tab 内容 -->
      <main ref="contentRef" class="content">
        <!-- 活动 -->
        <section v-if="activeTab === 'activity'">
          <div class="section-head">
            <h2>活动</h2>
            <label class="toggle">
              <input type="checkbox" v-model="includeFeed"> 包含犇犇
            </label>
          </div>
          <ul v-if="activity && activity.length" class="activity-list">
            <li v-for="(a, idx) in activity" :key="idx" :class="`act-${a.kind}`">
              <span class="kind-tag">{{ a.kind }}</span>
              <span class="time">{{ smart(a.time) }}</span>
              <template v-if="a.kind === 'feed'">
                <div class="lg-content" v-html="feedHtml(a.feed_content || '')" />
              </template>
              <template v-else-if="a.kind === 'article'">
                <NuxtLink :to="`/article/${a.article_id}`">{{ a.article_title || a.article_id }}</NuxtLink>
              </template>
              <template v-else-if="a.kind === 'paste'">
                <NuxtLink :to="`/paste/${a.paste_id}`">剪贴板 {{ a.paste_id }}</NuxtLink>
              </template>
              <template v-else-if="a.kind === 'judgement'">
                <span class="judgement-reason">{{ a.judgement_reason }}</span>
              </template>
            </li>
          </ul>
          <p v-else class="empty">暂无活动记录</p>
        </section>

        <!-- 个人介绍 -->
        <section v-if="activeTab === 'intro'">
          <h2>个人介绍</h2>
          <article class="lg-content" v-html="introHtml" />
        </section>

        <!-- OI 获奖 -->
        <section v-if="activeTab === 'prizes'">
          <h2>OI 获奖</h2>
          <ul class="simple-list">
            <li v-for="p in profile.prizes" :key="`${p.year}-${p.contest}-${p.prize}`">
              {{ p.year }} {{ p.contest }}
              <template v-if="p.event"> · {{ p.event }}</template>
              · {{ p.prize }}
            </li>
          </ul>
        </section>

        <!-- 用户名历史 -->
        <section v-if="activeTab === 'names'">
          <h2>用户名历史</h2>
          <ul class="simple-list">
            <li v-for="h in profile.name_history" :key="h.name">
              <span v-if="h.is_hidden" class="hidden-name">UID {{ profile.uid }}（已隐藏）</span>
              <span v-else class="lg-name" :data-color="profile.color">{{ h.name }}</span>
              <span class="time">{{ format(h.first_seen_at, 'YYYY-MM-DD') }} ~ {{ format(h.last_seen_at, 'YYYY-MM-DD') }}</span>
            </li>
          </ul>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
/* 脱离全局 .container 的 1200px 居中限制，做真·全宽两栏 */
.user-page {
  margin-left: calc(50% - 50vw + 56px);
  margin-right: calc(50% - 50vw);
  padding: 0 32px;
  box-sizing: border-box;
}
@media (max-width: 768px) {
  .user-page {
    margin-left: 0;
    margin-right: 0;
    padding: 0;
  }
}

.two-col {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 32px;
  margin-top: 16px;
  align-items: start;
}
@media (max-width: 768px) {
  .two-col { grid-template-columns: 1fr; }
}

.sidebar {
  position: sticky;
  top: 16px;
  align-self: start;
}

.profile-head {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px 16px;
  text-align: center;
  margin-bottom: 12px;
}
.avatar {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  border: 2px solid var(--border);
}
.name-row {
  margin: 10px 0 4px;
  font-size: 20px;
}
.slogan {
  color: var(--text-muted);
  margin: 4px 0 12px;
  font-size: 14px;
}
.badges {
  display: flex;
  justify-content: center;
  gap: 6px;
  margin-bottom: 12px;
}
.tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--hover);
  color: var(--text-muted);
}
.tag.banned { background: #ffecec; color: var(--lg-red); }
.tag.admin { background: #e9f5ff; color: var(--lg-blue); }

.stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
  margin: 14px 0 0;
  text-align: left;
}
.stats > div {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 5px 10px;
}
.stats dt { font-size: 11px; color: var(--text-muted); margin: 0; }
.stats dd { margin: 0; font-weight: 600; font-size: 14px; }

.tabs {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px;
}
.tabs button {
  padding: 8px 12px;
  border: none;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  border-radius: 4px;
  font: inherit;
}
.tabs button:hover { background: var(--hover); }
.tabs button.active {
  background: var(--link);
  color: #fff;
}

.content {
  min-width: 0;
  max-width: 820px;
  margin: 0 auto;
  width: 100%;
}
.content h2 { margin-top: 0; }
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.section-head h2 { margin: 0; }
.toggle {
  font-size: 14px;
  color: var(--text-muted);
}

.activity-list,
.simple-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.activity-list li,
.simple-list li {
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 8px;
}
.kind-tag {
  font-size: 11px;
  padding: 2px 8px;
  background: var(--hover);
  color: var(--text-muted);
  border-radius: 10px;
  margin-right: 8px;
}
.time {
  color: var(--text-muted);
  font-size: 13px;
  margin-left: 12px;
}
.hidden-name {
  color: var(--text-muted);
  font-style: italic;
}
.empty {
  color: var(--text-muted);
  text-align: center;
  padding: 40px;
}
.error-box {
  padding: 30px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  text-align: center;
}
</style>
