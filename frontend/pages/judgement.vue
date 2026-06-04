<script setup lang="ts">
const { smart } = useTime()

const api = useApi()

interface UserBrief {
  uid: number
  name: string
  color: string
  badge: string | null
  avatar: string | null
}
interface JudgementGroup {
  group_key: string
  reason: string
  revoked_permission: number
  added_permission: number
  time_start: string
  time_end: string
  users: UserBrief[]
  count: number
}

const PAGE_SIZE = 50

const groups = ref<JudgementGroup[]>([])
const loading = ref(false)
const noMore = ref(false)
// 游标：取下一页时把这个值塞 ?before=
const beforeTs = ref<string | null>(null)

// 首屏不等待后端：先显示页面，再拉第一页陶片。
const { data: firstPage, pending: firstPending } = useLazyAsyncData('judgement-first', () =>
  api<JudgementGroup[]>('/judgement', { query: { limit: PAGE_SIZE } }),
  { server: false },
)
const { data: lastCrawled } = useLazyAsyncData('judgement-last-crawled', () =>
  api<{ last_crawled_at: string | null }>('/last-crawled?type=judgement'),
  { server: false },
)

watch(firstPage, (page) => {
  if (!page) return
  groups.value = [...page]
  // 用 time_end 倒序拿下一页：取最后一组的 time_start 当游标。
  // 注意：不能用 length < PAGE_SIZE 判 noMore，后端先拉原始记录再合并分组。
  beforeTs.value = page.length ? page[page.length - 1].time_start : null
  noMore.value = page.length === 0
}, { immediate: true })

async function loadMore() {
  if (loading.value || noMore.value) return
  loading.value = true
  try {
    const q: Record<string, any> = { limit: PAGE_SIZE }
    if (beforeTs.value) q.before = beforeTs.value
    const page = await api<JudgementGroup[]>('/judgement', { query: q })
    if (page.length === 0) {
      noMore.value = true
    } else {
      // 去重：分页边界上同一条 judgement 可能在两页都被合并出来
      const seen = new Set(groups.value.map(g => g.group_key))
      const fresh = page.filter(g => !seen.has(g.group_key))
      groups.value.push(...fresh)
      beforeTs.value = page[page.length - 1].time_start
      // 同首屏，只有空页才判 noMore；group 数小于 PAGE_SIZE 是合并后的常态
    }
  } finally {
    loading.value = false
  }
}

/**
 * 洛谷权限位图。多个权限组合 = 数值相加（位或）。
 * 例：98304 = 32768 (自由发言) + 65536 (发送私信)。
 * 未确认的一律显示"未知位 (X)"，实测后逐步补齐。
 */
const PERMISSION_MAP: Array<[number, string]> = [
  [2, '进入主站'],
  [4, '进入后台'],
  [8, '题目管理'],
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

function formatTime(t: string): string {
  return smart(t)
}
</script>

<template>
  <div>
    <OriginBanner
      origin-url="https://www.luogu.com.cn/judgement"
      title="陶片放逐"
      :crawled-at="lastCrawled?.last_crawled_at"
      content-type="judgement"
      content-id="all"
    />

    <LoadingPanel v-if="firstPending && !groups.length" title="正在加载陶片放逐" text="页面已经打开，正在读取最新的封禁公示归档…" />

    <ul v-else-if="groups.length" class="list">
      <li v-for="g in groups" :key="g.group_key" class="item">
        <!-- 顶部：权限变更头标 + 时间 -->
        <header class="head">
          <span class="action-tag" :class="g.revoked_permission > 0 ? 'revoked' : 'added'">
            <template v-if="g.revoked_permission > 0 && g.added_permission === 0">
              撤销权限
            </template>
            <template v-else-if="g.added_permission > 0 && g.revoked_permission === 0">
              授予权限
            </template>
            <template v-else>
              权限变更
            </template>
          </span>
          <span v-if="g.count > 1" class="count">{{ g.count }} 人</span>
          <span class="time">{{ formatTime(g.time_end) }}</span>
        </header>

        <!-- 中间：用户（头像 + 大号名字） -->
        <div class="users">
          <NuxtLink
            v-for="u in g.users"
            :key="u.uid"
            :to="`/user/${u.uid}`"
            class="user-card"
          >
            <img
              v-if="u.avatar"
              :src="u.avatar"
              alt=""
              class="avatar"
              loading="lazy"
            >
            <div
              v-else
              class="avatar avatar-fallback"
              :data-color="u.color"
            >{{ (u.name || '?').charAt(0).toUpperCase() }}</div>
            <div class="name-wrap">
              <LuoguUserName :user="u" show-badge no-link />
            </div>
          </NuxtLink>
        </div>

        <!-- 下部：权限明细 -->
        <div class="perms">
          <div v-if="describePermission(g.revoked_permission).length" class="perm-row">
            <span class="perm-label revoked">● 撤销</span>
            <span v-for="p in describePermission(g.revoked_permission)" :key="`r-${p}`" class="perm-chip">{{ p }}</span>
            <span class="perm-suffix">权限</span>
          </div>
          <div v-if="describePermission(g.added_permission).length" class="perm-row">
            <span class="perm-label added">● 授予</span>
            <span v-for="p in describePermission(g.added_permission)" :key="`a-${p}`" class="perm-chip">{{ p }}</span>
            <span class="perm-suffix">权限</span>
          </div>
        </div>

        <!-- 最底：原因 -->
        <div class="reason">{{ g.reason }}</div>
      </li>
    </ul>
    <p v-else class="empty">暂无数据</p>

    <div v-if="groups.length" class="loader">
      <button v-if="!noMore" :disabled="loading" @click="loadMore">
        {{ loading ? '加载中...' : '加载更多' }}
      </button>
      <span v-else class="empty-line">没有更多了</span>
    </div>
  </div>
</template>

<style scoped>
.list {
  list-style: none;
  padding: 0;
}
.item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 14px;
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 顶部头标 */
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: var(--text-muted);
}
.action-tag {
  font-size: 13px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 4px;
}
.action-tag.revoked {
  color: var(--lg-red);
  background: transparent;
}
.action-tag.added {
  color: var(--lg-green);
  background: transparent;
}
.count {
  background: var(--lg-orange);
  color: white;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
}
.time {
  margin-left: auto;
  font-size: 13px;
  color: var(--text-muted);
}

/* 用户卡片 */
.users {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 12px 4px 4px;
  border-radius: 28px;
  color: inherit;
  text-decoration: none;
  transition: background 0.15s;
}
.user-card:hover {
  background: var(--hover);
  text-decoration: none;
}
.avatar {
  width: 40px;
  height: 40px;
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
  font-size: 16px;
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
.name-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 16px;
  font-weight: 600;
}

/* 权限明细 */
.perms {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-left: 8px;
}
.perm-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 14px;
}
.perm-label {
  font-weight: 500;
}
.perm-label.revoked { color: var(--lg-red); }
.perm-label.added   { color: var(--lg-green); }
.perm-chip {
  background: var(--hover);
  border: 1px solid var(--border);
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 13px;
}
.perm-suffix {
  color: var(--text-muted);
  font-size: 13px;
}

/* 原因 */
.reason {
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  color: var(--text);
}

.empty {
  text-align: center;
  color: var(--text-muted);
  padding: 40px;
}

.loader {
  text-align: center;
  padding: 20px;
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
.loader .empty-line {
  color: var(--text-muted);
}
</style>
