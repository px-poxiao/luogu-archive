<script setup lang="ts">
const route = useRoute()
const api = useApi()
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
const { data: activity, refresh: refreshActivity } = await useAsyncData(
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
</script>

<template>
  <div v-if="error" class="error-box">
    <h2>{{ error.data?.message || '用户未收录' }}</h2>
    <p>已触发一次爬取，稍等片刻刷新即可。</p>
  </div>

  <div v-else-if="profile">
    <OriginBanner
      :origin-url="`https://www.luogu.com.cn/user/${uid}`"
      :crawled-at="null"
      content-type="user"
      :content-id="String(uid)"
    />

    <section class="profile-head">
      <img
        v-if="profile.avatar"
        :src="profile.avatar"
        class="avatar"
        alt=""
      >
      <div class="info">
        <h1>
          <LuoguUserName :user="userBrief" :hidden="profile.name_hidden" show-badge no-link />
          <span v-if="profile.is_banned" class="tag banned">已封禁</span>
          <span v-if="profile.is_admin" class="tag admin">管理员</span>
          <FollowButton :uid="profile.uid" />
        </h1>
        <p v-if="profile.slogan" class="slogan">{{ profile.slogan }}</p>
        <dl class="stats">
          <div><dt>关注</dt><dd>{{ profile.following_count }}</dd></div>
          <div><dt>粉丝</dt><dd>{{ profile.follower_count }}</dd></div>
          <div v-if="profile.ranking !== null"><dt>做题榜</dt><dd>#{{ profile.ranking }}</dd></div>
          <div v-if="profile.ccf_level > 0"><dt>CCF 等级</dt><dd>{{ profile.ccf_level }}</dd></div>
          <div v-if="profile.xcpc_level > 0"><dt>XCPC</dt><dd>{{ profile.xcpc_level }}</dd></div>
        </dl>
      </div>
    </section>

    <!-- 名字历史：管理员视角显示所有，普通访客 hidden 的显示为 UID xxx -->
    <section v-if="profile.name_history.length > 1" class="name-history">
      <h2>用户名历史</h2>
      <ul>
        <li v-for="h in profile.name_history" :key="h.name">
          <span v-if="h.is_hidden" class="hidden-name">UID {{ profile.uid }}（已隐藏）</span>
          <span v-else class="lg-name" :data-color="profile.color">{{ h.name }}</span>
          <span class="time">{{ h.first_seen_at }} ~ {{ h.last_seen_at }}</span>
        </li>
      </ul>
    </section>

    <!-- 奖项 -->
    <section v-if="profile.prizes.length" class="prizes">
      <h2>OI 获奖</h2>
      <ul>
        <li v-for="p in profile.prizes" :key="`${p.year}-${p.contest}-${p.prize}`">
          {{ p.year }} {{ p.contest }}
          <template v-if="p.event"> · {{ p.event }}</template>
          · {{ p.prize }}
        </li>
      </ul>
    </section>

    <!-- 个人介绍 -->
    <section v-if="profile.introduction_md" class="intro">
      <h2>个人介绍</h2>
      <article class="lg-content" v-html="introHtml" />
    </section>

    <!-- 活动流 -->
    <section class="activity">
      <h2>
        活动
        <label class="toggle">
          <input type="checkbox" v-model="includeFeed"> 包含犇犇
        </label>
      </h2>
      <ul v-if="activity && activity.length">
        <li v-for="(a, idx) in activity" :key="idx" :class="`act-${a.kind}`">
          <span class="kind-tag">{{ a.kind }}</span>
          <span class="time">{{ a.time }}</span>
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
  </div>
</template>

<style scoped>
.profile-head {
  display: flex;
  gap: 20px;
  align-items: flex-start;
  margin-bottom: 24px;
}
.avatar {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  border: 2px solid var(--border);
}
.info h1 {
  margin: 0 0 6px;
  font-size: 28px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.slogan {
  color: var(--text-muted);
  margin: 0 0 12px;
}
.stats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin: 0;
}
.stats > div {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 12px;
}
.stats dt { font-size: 12px; color: var(--text-muted); margin: 0; }
.stats dd { margin: 0; font-weight: 600; }

.tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--hover);
  color: var(--text-muted);
}
.tag.banned { background: #ffecec; color: var(--lg-red); }
.tag.admin { background: #e9f5ff; color: var(--lg-blue); }

.name-history ul,
.prizes ul,
.activity ul {
  list-style: none;
  padding: 0;
}
.name-history li,
.prizes li,
.activity li {
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 8px;
}
.hidden-name {
  color: var(--text-muted);
  font-style: italic;
}
.time {
  color: var(--text-muted);
  font-size: 13px;
  margin-left: 12px;
}
.kind-tag {
  font-size: 11px;
  padding: 2px 8px;
  background: var(--hover);
  color: var(--text-muted);
  border-radius: 10px;
  margin-right: 8px;
}
.toggle {
  font-size: 14px;
  font-weight: normal;
  margin-left: 16px;
}
.empty {
  color: var(--text-muted);
}
</style>
