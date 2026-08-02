<script setup lang="ts">
const route = useRoute()
const api = useApi()
const { smart, format } = useTime()
const uid = route.params.uid as string

interface UserNameHistoryItem {
  name: string
  color: string
  badge: string | null
  ccf_level: number
  xcpc_level: number
  first_seen_at: string
  last_seen_at: string
  is_hidden: boolean
}

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
  name_history: UserNameHistoryItem[]
  prizes: Array<{ year: number; contest: string; event: string | null; prize: string; score: number | null; rank: number | null }>
  name_hidden: boolean
}

interface ActivityItem {
  kind: string
  time: string
  feed_id?: number
  feed_content?: string
  feed_merged_suffix_md?: string | null
  feed_merged_from_id?: number | null
  feed_merged_link_md?: string[]
  article_id?: string
  article_title?: string
  paste_id?: string
  judgement_reason?: string
  judgement_revoked?: number
  judgement_added?: number
}

// 活动种类的中文标签
const KIND_LABEL: Record<string, string> = {
  feed: '动态',
  article: '文章',
  paste: '剪贴板',
  judgement: '陶片放逐',
}

// 陶片权限位图（沿用陶片页的常量，单点维护建议后续抽 composable）
const PERMISSION_MAP: Array<[number, string]> = [
  [1, '登录授权'],
  [2, '进入主站'],
  [4, '进入后台'],
  [8, '题目管理'],
  [16, '团队管理'],
  [32, '比赛管理'],
  [64, '讨论管理'],
  [256, '用户管理'],
  [512, '专栏管理'],
  [32768, '自由发言'],
  [65536, '发送私信'],
  [131072, '使用专栏'],
  [524288, '使用图床'],
  [2097152, '题目志愿者'],
  [4194304, '专栏志愿者'],
]

function describePermission(bits: number): string[] {
  if (!bits) return []
  const out: string[] = []
  let remaining = bits
  for (const [v, label] of PERMISSION_MAP) {
    if ((bits & v) === v) {
      out.push(label)
      remaining &= ~v
    }
  }
  if (remaining) out.push(`未知位 (${remaining})`)
  return out
}

// 用户页不阻塞首屏：资料回来前先显示加载窗口。
const { data: profile, error, pending: profilePending } = useLazyAsyncData(`user-${uid}`, () =>
  api<UserProfile>(`/user/${uid}`),
  { server: false },
)

const includeFeed = ref(true)
// 活动列表分页：游标 = 列表最后一条的 time（更老的时间）
const activity = ref<ActivityItem[]>([])
const activityLoading = ref(false)
const activityNoMore = ref(false)
const activityBefore = ref<string | null>(null)
const PAGE_SIZE = 50

// 活动第一页同样懒加载，避免用户资料页等待活动接口。
const { data: firstPage, pending: activityInitialPending } = useLazyAsyncData(
  `user-activity-${uid}`,
  () =>
    api<ActivityItem[]>(`/user/${uid}/activity`, {
      query: { include_feed: includeFeed.value ? 'true' : 'false', limit: PAGE_SIZE },
    }),
  { server: false },
)

watch(firstPage, (page) => {
  if (!page) return
  activity.value = [...page]
  activityBefore.value = page.length ? page[page.length - 1].time : null
  activityNoMore.value = page.length < PAGE_SIZE
}, { immediate: true })

async function loadMoreActivity() {
  if (activityLoading.value || activityNoMore.value) return
  activityLoading.value = true
  try {
    const q: Record<string, any> = {
      include_feed: includeFeed.value ? 'true' : 'false',
      limit: PAGE_SIZE,
    }
    if (activityBefore.value) q.before = activityBefore.value
    const page = await api<ActivityItem[]>(`/user/${uid}/activity`, { query: q })
    if (page.length === 0) {
      activityNoMore.value = true
    } else {
      activity.value.push(...page)
      activityBefore.value = page[page.length - 1].time
      if (page.length < PAGE_SIZE) activityNoMore.value = true
    }
  } finally {
    activityLoading.value = false
  }
}

// 切换"包含动态"开关 → 重置 + 拉第一页
watch(includeFeed, async () => {
  activity.value = []
  activityBefore.value = null
  activityNoMore.value = false
  activityLoading.value = true
  try {
    const page = await api<ActivityItem[]>(`/user/${uid}/activity`, {
      query: { include_feed: includeFeed.value ? 'true' : 'false', limit: PAGE_SIZE },
    })
    activity.value = page
    if (page.length === 0) {
      activityNoMore.value = true
    } else {
      activityBefore.value = page[page.length - 1].time
      if (page.length < PAGE_SIZE) activityNoMore.value = true
    }
  } finally {
    activityLoading.value = false
  }
})

const { render } = useMarkdown()
const introHtml = computed(() =>
  profile.value?.introduction_md ? render(profile.value.introduction_md) : '',
)
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

function feedHtml(content: string, mergedSuffix?: string | null, mergedLinks: string[] = []) {
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

const copiedIntroOriginal = ref(false)
async function copyIntroOriginal() {
  if (!profile.value?.introduction_md) return
  await navigator.clipboard.writeText(profile.value.introduction_md)
  copiedIntroOriginal.value = true
  setTimeout(() => { copiedIntroOriginal.value = false }, 1400)
}

const userBrief = computed(() => profile.value ? {
  uid: profile.value.uid,
  name: profile.value.name,
  color: profile.value.color,
  badge: profile.value.badge,
  avatar: profile.value.avatar,
  ccf_level: profile.value.ccf_level,
  xcpc_level: profile.value.xcpc_level,
  is_admin: profile.value.is_admin,
} : null)

interface CollapsedNameHistoryItem extends UserNameHistoryItem {
  id: string
}

// 兼容旧数据：只合并时间线上相邻且外显完全相同的快照，不跨越中间变化。
const nameHistory = computed<CollapsedNameHistoryItem[]>(() => {
  const ordered = [...(profile.value?.name_history ?? [])].sort(
    (a, b) => new Date(b.first_seen_at).getTime() - new Date(a.first_seen_at).getTime(),
  )
  const collapsed: CollapsedNameHistoryItem[] = []

  for (const entry of ordered) {
    const key = [
      entry.is_hidden ? 'hidden' : entry.name,
      entry.color,
      entry.badge ?? '',
      entry.ccf_level,
      entry.xcpc_level,
    ].join('|')
    const tail = collapsed[collapsed.length - 1]
    const tailKey = tail
      ? [
          tail.is_hidden ? 'hidden' : tail.name,
          tail.color,
          tail.badge ?? '',
          tail.ccf_level,
          tail.xcpc_level,
        ].join('|')
      : null

    if (tail && tailKey === key) {
      if (new Date(entry.first_seen_at) < new Date(tail.first_seen_at)) {
        tail.first_seen_at = entry.first_seen_at
      }
      if (new Date(entry.last_seen_at) > new Date(tail.last_seen_at)) {
        tail.last_seen_at = entry.last_seen_at
      }
      continue
    }

    collapsed.push({
      ...entry,
      id: `${entry.first_seen_at}-${collapsed.length}`,
    })
  }
  return collapsed
})

function historyUser(entry: UserNameHistoryItem) {
  return {
    uid: profile.value?.uid ?? Number(uid),
    name: entry.name,
    color: entry.color,
    badge: entry.badge,
    avatar: null,
    ccf_level: entry.ccf_level,
    xcpc_level: entry.xcpc_level,
  }
}

// 左侧 Tab 切换
type TabKey = 'activity' | 'intro' | 'prizes' | 'names'
const activeTab = ref<TabKey>('activity')

const tabs: Array<{ key: TabKey; label: string; show: () => boolean }> = [
  { key: 'activity', label: '活动', show: () => true },
  { key: 'intro', label: '个人介绍', show: () => !!profile.value?.introduction_md },
  { key: 'prizes', label: 'OI 获奖', show: () => (profile.value?.prizes?.length ?? 0) > 0 },
  { key: 'names', label: '用户名历史', show: () => nameHistory.value.length > 1 },
]

// 代码复制按钮：绑在右侧内容容器上，覆盖 activity / intro 两种 md 场景
const contentRef = ref<HTMLElement | null>(null)
useCopyCode(contentRef)

// XCPC 的 score 是浮点（penalty 算法），OI 是整数；整数原样、浮点保留 2 位小数
function formatScore(s: number): string {
  return Number.isInteger(s) ? String(s) : s.toFixed(2)
}
</script>

<template>
  <LoadingPanel v-if="profilePending" title="正在加载用户档案" text="页面已经打开，正在读取用户资料和活动记录…" />

  <div v-else-if="error" class="error-box">
    <h2>{{ error.data?.message || '用户未收录' }}</h2>
    <p>已触发一次爬取，稍等片刻刷新即可。</p>
  </div>

  <div v-else-if="profile" class="user-page">
    <OriginBanner
      :origin-url="`https://www.luogu.com.cn/user/${uid}`"
      compact
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
          <NuxtLink :to="`/user/${profile.uid}/card`" class="card-link-btn">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M4 19V5M9 19v-8M14 19v-5M19 19V9M3 19h18"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span>图卡</span>
          </NuxtLink>

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
              <input type="checkbox" v-model="includeFeed"> 包含动态
            </label>
          </div>
          <LoadingPanel
            v-if="activityInitialPending && !activity.length"
            title="正在加载活动记录"
            text="用户资料已经打开，正在读取活动时间线…"
          />

          <ul v-else-if="activity && activity.length" class="activity-list">
            <li v-for="(a, idx) in activity" :key="idx" :class="`act-${a.kind}`">
              <span class="kind-tag">{{ KIND_LABEL[a.kind] || a.kind }}</span>
              <span class="time">{{ smart(a.time) }}</span>
              <template v-if="a.kind === 'feed'">
                <div
                  class="lg-content"
                  v-html="feedHtml(a.feed_content || '', a.feed_merged_suffix_md, a.feed_merged_link_md || [])"
                />
                <div class="feed-foot">
                  <span class="feed-id">#{{ a.feed_id }}</span>
                  <FeedReplyButton
                    :content="a.feed_content || ''"
                    :sender-name="profile.name_hidden ? `UID ${profile.uid}` : profile.name"
                  />
                </div>
              </template>
              <template v-else-if="a.kind === 'article'">
                <div class="link-line">
                  <NuxtLink :to="`/article/${a.article_id}`">{{ a.article_title || a.article_id }}</NuxtLink>
                </div>
              </template>
              <template v-else-if="a.kind === 'paste'">
                <div class="link-line">
                  <NuxtLink :to="`/paste/${a.paste_id}`">剪贴板 {{ a.paste_id }}</NuxtLink>
                </div>
              </template>
              <template v-else-if="a.kind === 'judgement'">
                <div class="judgement-card">
                  <header class="head">
                    <span
                      class="action-tag"
                      :class="(a.judgement_revoked ?? 0) === 0 && (a.judgement_added ?? 0) === 0
                        ? 'cheater'
                        : ((a.judgement_revoked ?? 0) > 0 ? 'revoked' : 'added')"
                    >
                      <template v-if="(a.judgement_revoked ?? 0) > 0 && (a.judgement_added ?? 0) === 0">
                        撤销权限
                      </template>
                      <template v-else-if="(a.judgement_added ?? 0) > 0 && (a.judgement_revoked ?? 0) === 0">
                        授予权限
                      </template>
                      <template v-else-if="(a.judgement_revoked ?? 0) === 0 && (a.judgement_added ?? 0) === 0">
                        棕名惩罚
                      </template>
                      <template v-else>
                        权限变更
                      </template>
                    </span>
                  </header>

                  <div v-if="describePermission(a.judgement_revoked ?? 0).length" class="perm-row">
                    <span class="perm-label revoked">● 撤销</span>
                    <span
                      v-for="p in describePermission(a.judgement_revoked ?? 0)"
                      :key="`r-${idx}-${p}`"
                      class="perm-chip"
                    >{{ p }}</span>
                    <span class="perm-suffix">权限</span>
                  </div>
                  <div v-if="describePermission(a.judgement_added ?? 0).length" class="perm-row">
                    <span class="perm-label added">● 授予</span>
                    <span
                      v-for="p in describePermission(a.judgement_added ?? 0)"
                      :key="`a-${idx}-${p}`"
                      class="perm-chip"
                    >{{ p }}</span>
                    <span class="perm-suffix">权限</span>
                  </div>

                  <div class="reason">{{ a.judgement_reason }}</div>
                </div>
              </template>
            </li>
          </ul>
          <p v-else class="empty">暂无活动记录</p>

          <!-- 加载更多 -->
          <div v-if="activity && activity.length" class="loader">
            <button v-if="!activityNoMore" :disabled="activityLoading" @click="loadMoreActivity">
              {{ activityLoading ? '加载中...' : '加载更多' }}
            </button>
            <span v-else class="empty">没有更多了</span>
          </div>
        </section>

        <!-- 个人介绍 -->
        <section v-if="activeTab === 'intro'">
          <div class="section-head">
            <h2>个人介绍</h2>
            <button type="button" class="section-action-btn" @click="copyIntroOriginal">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M8 8h10v12H8zM6 16H4V4h12v2"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linejoin="round"
                />
              </svg>
              <span>{{ copiedIntroOriginal ? '已复制' : '复制原文' }}</span>
            </button>
          </div>
          <article class="lg-content" v-html="introHtml" />
        </section>

        <!-- OI 获奖 -->
        <section v-if="activeTab === 'prizes'">
          <h2>OI 获奖</h2>
          <table class="prize-table">
            <thead>
              <tr>
                <th>年份</th>
                <th>赛事</th>
                <th>项目</th>
                <th>奖项</th>
                <th>分数</th>
                <th>排名</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(p, idx) in profile.prizes" :key="`${idx}-${p.contest}-${p.prize}`">
                <td>
                  <template v-if="p.year && p.year > 0">{{ p.year }}</template>
                  <span v-else class="hidden-cell">已隐藏</span>
                </td>
                <td>{{ p.contest }}</td>
                <td>{{ p.event || '—' }}</td>
                <td>{{ p.prize }}</td>
                <!-- score/rank 都为 null：合并两格，"已隐藏"在两列范围内居中 -->
                <td v-if="p.score === null && p.rank === null"
                    colspan="2" class="hidden-cell hidden-merged">已隐藏</td>
                <template v-else>
                  <td>{{ p.score !== null ? formatScore(p.score) : '—' }}</td>
                  <td>{{ p.rank !== null ? p.rank : '—' }}</td>
                </template>
              </tr>
            </tbody>
          </table>
        </section>

        <!-- 用户名外显历史 -->
        <section v-if="activeTab === 'names'" class="name-history-panel">
          <header class="name-history-head">
            <div>
              <h2>历史用户名外显</h2>
              <p>追踪最近的用户名外显变动记录。</p>
            </div>
            <span>{{ nameHistory.length }} 次记录</span>
          </header>

          <ol class="name-history-list">
            <li
              v-for="(h, index) in nameHistory"
              :key="h.id"
              :class="{ current: index === 0 }"
            >
              <span class="history-line" aria-hidden="true" />
              <span class="history-dot" aria-hidden="true" />
              <div class="history-content">
                <LuoguUserName
                  :user="historyUser(h)"
                  :hidden="h.is_hidden"
                  show-badge
                  no-link
                />
                <div class="history-time">
                  <span :title="h.first_seen_at">
                    最早追溯到 {{ format(h.first_seen_at, 'YYYY/MM/DD') }}
                  </span>
                  <span :title="h.last_seen_at">
                    最后捕获于 {{ format(h.last_seen_at, 'YYYY/MM/DD') }}
                  </span>
                </div>
              </div>
            </li>
          </ol>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.user-page {
  width: 100%;
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

.two-col {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 32px;
  margin-top: 16px;
  align-items: start;
}
@media (max-width: 768px) {
  .two-col { grid-template-columns: 1fr; gap: 16px; }
}

.sidebar {
  position: sticky;
  top: 16px;
  align-self: start;
}
@media (max-width: 768px) {
  /* 手机端：sidebar 变普通块，跟随页面向上滚出视口；tab 横向铺开 */
  .sidebar {
    position: static;
    top: auto;
  }
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

.card-link-btn {
  width: fit-content;
  margin: 10px auto 0;
  padding: 6px 16px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  text-decoration: none;
  font-size: 14px;
}
.card-link-btn:hover {
  border-color: var(--link);
  color: var(--link);
  text-decoration: none;
}
.card-link-btn svg {
  width: 15px;
  height: 15px;
  flex: 0 0 auto;
}
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

@media (max-width: 768px) {
  /* 手机端 tab 横向铺开，便于一行选 */
  .tabs {
    flex-direction: row;
    flex-wrap: wrap;
  }
  .tabs button {
    flex: 1 0 auto;
    text-align: center;
  }
}

.content {
  min-width: 0;
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
.section-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  transition: border-color 0.15s, color 0.15s, transform 0.1s;
}
.section-action-btn:hover {
  border-color: var(--link);
  color: var(--link);
  transform: translateY(-1px);
}
.section-action-btn svg {
  width: 15px;
  height: 15px;
  flex: 0 0 auto;
}

.activity-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.activity-list li {
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
.link-line {
  /* 文章 / 剪贴板的链接独占一行，上方留空与 feed 内容块保持一致 */
  margin-top: 8px;
}
.name-history-panel {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}
.name-history-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border);
}
.name-history-head h2 {
  margin: 0;
  font-size: 18px;
}
.name-history-head p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.name-history-head > span {
  flex: 0 0 auto;
  color: var(--text-muted);
  font-size: 12px;
}
.name-history-list {
  margin: 0;
  padding: 8px 22px 12px;
  list-style: none;
}
.name-history-list li {
  position: relative;
  min-height: 66px;
  padding: 13px 0 13px 26px;
}
.history-line {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 5px;
  width: 1px;
  background: var(--border);
}
.name-history-list li:first-child .history-line {
  top: 21px;
}
.name-history-list li:last-child .history-line {
  bottom: calc(100% - 22px);
}
.history-dot {
  position: absolute;
  top: 19px;
  left: 1px;
  width: 9px;
  height: 9px;
  box-sizing: border-box;
  border: 2px solid var(--surface);
  border-radius: 50%;
  background: var(--text-muted);
  box-shadow: 0 0 0 1px var(--border);
}
.name-history-list li.current .history-dot {
  background: var(--link);
  box-shadow: 0 0 0 1px var(--link);
}
.history-content {
  min-width: 0;
}
.history-time {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 16px;
  margin-top: 7px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.4;
}
.name-history-list li.current .history-time {
  color: var(--text);
  font-weight: 500;
}
@media (max-width: 520px) {
  .name-history-head {
    padding: 16px;
  }
  .name-history-head > span {
    display: none;
  }
  .name-history-list {
    padding-right: 16px;
    padding-left: 16px;
  }
}
.feed-foot {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 自动补回的回复后缀用下划线区分，避免用户误以为是原回复正文。 */
.lg-content :deep(.feed-auto-merged) {
  text-decoration-line: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.lg-content :deep(.feed-auto-merged img) {
  box-shadow: 0 2px 0 currentColor;
}
.lg-content :deep(.feed-auto-merged-link),
.lg-content :deep(.feed-auto-merged-link a) {
  text-decoration-line: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.feed-id {
  font-size: 11px;
  color: var(--text-muted);
  font-family: ui-monospace, "SF Mono", Consolas, monospace;
  opacity: 0.55;
}

/* 陶片放逐迷你卡片（沿用陶片页样式，但不带头像名字） */
.judgement-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 6px;
}
.judgement-card .head {
  display: flex;
  align-items: center;
}
.judgement-card .action-tag {
  font-size: 13px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 4px;
}
.judgement-card .action-tag.revoked { color: var(--lg-red); }
.judgement-card .action-tag.added { color: var(--lg-green); }
.judgement-card .action-tag.cheater { color: var(--lg-cheater-tag); }
.judgement-card .perm-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 14px;
  padding-left: 8px;
}
.judgement-card .perm-label { font-weight: 500; }
.judgement-card .perm-label.revoked { color: var(--lg-red); }
.judgement-card .perm-label.added { color: var(--lg-green); }
.judgement-card .perm-chip {
  background: var(--hover);
  border: 1px solid var(--border);
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 13px;
}
.judgement-card .perm-suffix {
  color: var(--text-muted);
  font-size: 13px;
}
.judgement-card .reason {
  padding-top: 6px;
  border-top: 1px dashed var(--border);
  color: var(--text);
  font-size: 14px;
}
.empty {
  color: var(--text-muted);
  text-align: center;
  padding: 40px;
}
.prize-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  font-size: 14px;
}
.prize-table th,
.prize-table td {
  padding: 8px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.prize-table thead {
  background: var(--hover);
}
.prize-table th {
  font-weight: 600;
  color: var(--text-muted);
  font-size: 13px;
}
.prize-table tbody tr:last-child td {
  border-bottom: none;
}
.prize-table tbody tr:hover {
  background: var(--hover);
}
.hidden-cell {
  color: var(--text-muted);
  font-size: 13px;
}
.prize-table td.hidden-merged {
  text-align: center;
}
.loader {
  text-align: center;
  padding: 16px 0;
}
.loader button {
  padding: 8px 24px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  color: var(--text);
  font: inherit;
}
.loader button:hover:not(:disabled) {
  border-color: var(--link);
  color: var(--link);
}
.loader button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.loader .empty {
  padding: 8px;
}
.error-box {
  padding: 30px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  text-align: center;
}
</style>
