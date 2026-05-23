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
  [2, '进入主站'],
  [4, '进入后台'],
  [32768, '自由发言'],
  [65536, '发送私信'],
  [131072, '使用专栏'],
  [524288, '使用图床'],
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

const { data: profile, error } = await useAsyncData(`user-${uid}`, () =>
  api<UserProfile>(`/user/${uid}`),
)

const includeFeed = ref(true)
// 活动列表分页：游标 = 列表最后一条的 time（更老的时间）
const activity = ref<ActivityItem[]>([])
const activityLoading = ref(false)
const activityNoMore = ref(false)
const activityBefore = ref<string | null>(null)
const PAGE_SIZE = 50

// SSR 首屏：useAsyncData 拿第一页，序列化到 payload，client hydrate 不会重跑。
// 之前犯的错：把 ref 修改写在 handler 里 —— 那只在 SSR 阶段执行；client
// 直接读 payload，外部 ref 永远是空。这里改回让 useAsyncData 自管 data ref，
// 在客户端用 watchEffect 同步到 activity ref 作为初值。
const { data: firstPage } = await useAsyncData(
  `user-activity-${uid}`,
  () =>
    api<ActivityItem[]>(`/user/${uid}/activity`, {
      query: { include_feed: includeFeed.value ? 'true' : 'false', limit: PAGE_SIZE },
    }),
)

if (firstPage.value && firstPage.value.length) {
  activity.value = [...firstPage.value]
  activityBefore.value = firstPage.value[firstPage.value.length - 1].time
  if (firstPage.value.length < PAGE_SIZE) activityNoMore.value = true
} else {
  activityNoMore.value = true
}

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
function feedHtml(c: string) { return render(c) }

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
              <input type="checkbox" v-model="includeFeed"> 包含动态
            </label>
          </div>
          <ul v-if="activity && activity.length" class="activity-list">
            <li v-for="(a, idx) in activity" :key="idx" :class="`act-${a.kind}`">
              <span class="kind-tag">{{ KIND_LABEL[a.kind] || a.kind }}</span>
              <span class="time">{{ smart(a.time) }}</span>
              <template v-if="a.kind === 'feed'">
                <div class="lg-content" v-html="feedHtml(a.feed_content || '')" />
                <div class="feed-id">#{{ a.feed_id }}</div>
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
                      :class="(a.judgement_revoked ?? 0) > 0 ? 'revoked' : 'added'"
                    >
                      <template v-if="(a.judgement_revoked ?? 0) > 0 && (a.judgement_added ?? 0) === 0">
                        撤销权限
                      </template>
                      <template v-else-if="(a.judgement_added ?? 0) > 0 && (a.judgement_revoked ?? 0) === 0">
                        授予权限
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
/*
  用户页要 break out 父级 .container（max-width:1200, margin:auto, padding:28 40 56），
  让 sidebar 永远紧贴左边栏。在所有分辨率下三段视觉距离都 = 40px：
    左边栏右沿 → sidebar 左 = 40
    sidebar 右 → content 左 = 40 (grid gap)
    content 右 → viewport 右 = 40

  break out 公式：宽 = 100vw - 56(左边栏)；
  左偏移 = 父 .main-area 自身距 layout-body 左边的距离。
  .main-area 距 layout-body 左边 = max(0, (100vw-56-1200)/2) + 40px(.main-area padding-left)。
  右偏移同理（反过来抵消父级 padding-right）。
*/
.user-page {
  width: calc(100vw - 56px);
  margin-left: calc(-40px - max(0px, (100vw - 56px - 1200px) / 2));
  margin-right: calc(-40px - max(0px, (100vw - 56px - 1200px) / 2));
  padding: 0 40px;
  box-sizing: border-box;
}
@media (max-width: 768px) {
  .user-page {
    width: 100%;
    margin-left: 0;
    margin-right: 0;
    padding: 0;
  }
}

.two-col {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 40px;
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
.link-line {
  /* 文章 / 剪贴板的链接独占一行，上方留空与 feed 内容块保持一致 */
  margin-top: 8px;
}
.hidden-name {
  color: var(--text-muted);
  font-style: italic;
}
.feed-id {
  margin-top: 6px;
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
