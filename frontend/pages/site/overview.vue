<script setup lang="ts">
const api = useApi()
const { format, smart } = useTime()

interface SiteTotals {
  crawl_tasks: number
  articles: number
  pastes: number
  feeds: number
  judgements: number
}

interface QueueInfo {
  key: string
  label: string
  size: number
}

interface RecentTaskItem {
  id: number
  task_type: string
  target: string
  trigger: string
  status: string
  started_at: string
}

interface SiteOverview {
  generated_at: string
  totals: SiteTotals
  queues: QueueInfo[]
  recent_tasks: RecentTaskItem[]
}

const refreshing = ref(false)

const { data, pending, error, refresh } = useLazyAsyncData('site-overview', () =>
  api<SiteOverview>('/site/overview'),
  { server: false },
)

const { pause, resume } = useIntervalFn(() => {
  refreshOverview()
}, 10_000, { immediate: false })

onMounted(() => resume())
onBeforeUnmount(() => pause())

async function refreshOverview() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await refresh()
  } finally {
    refreshing.value = false
  }
}

const metricCards = computed(() => {
  const totals = data.value?.totals
  return [
    { key: 'crawl_tasks', label: '总保存任务', value: totals?.crawl_tasks ?? 0, icon: 'M5 12l4 4L19 6M5 20h14M5 4h14' },
    { key: 'articles', label: '文章', value: totals?.articles ?? 0, icon: 'M6 4h10l4 4v12H6V4zM9 13h6M9 17h7' },
    { key: 'pastes', label: '剪贴板', value: totals?.pastes ?? 0, icon: 'M9 4h6l1 2h3v14H5V6h3l1-2zM9 11h6M9 15h6' },
    { key: 'feeds', label: '犇犇', value: totals?.feeds ?? 0, icon: 'M4 5h16v10H7l-3 3V5z' },
    { key: 'judgements', label: '陶片记录', value: totals?.judgements ?? 0, icon: 'M4 14l6-6 4 4 6-6M4 20h16' },
  ]
})

const maxQueueSize = computed(() =>
  Math.max(1, ...(data.value?.queues.map(q => q.size) ?? [0])),
)

function numberText(value: number): string {
  return value.toLocaleString('zh-CN')
}

function queuePressure(size: number): number {
  if (size <= 0) return 0
  return Math.max(4, Math.round((size / maxQueueSize.value) * 100))
}

function typeLabel(type: string): string {
  const map: Record<string, string> = {
    article: '文章',
    paste: '剪贴板',
    feed: '犇犇',
    judgement: '陶片',
    user: '用户',
    problem: '题目',
    problem_list: '题目列表',
    problem_solution: '题解状态',
    contest: '比赛',
    contest_scoreboard: '比赛榜单',
  }
  return map[type] || type
}

function triggerLabel(trigger: string): string {
  const map: Record<string, string> = {
    manual: '手动',
    scheduled: '定时',
    passive: '访问触发',
    realtime: '实时监听',
    discovery: '入口发现',
    internal: '内部调度',
  }
  return map[trigger] || trigger
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '等待中',
    running: '运行中',
    success: '成功',
    failed: '失败',
    skipped: '已跳过',
    rate_limited: '限流',
  }
  return map[status] || status
}
</script>

<template>
  <div class="overview-page">
    <PageHero
      title="站点概览"
      subtitle="归档内容与后台处理通道的实时数据"
    >
      <template #extra>
        <div class="hero-actions">
          <span class="refresh-time">
            {{ data?.generated_at ? `更新于 ${format(data.generated_at, 'HH:mm:ss')}` : '等待数据' }}
          </span>
          <button type="button" class="refresh-btn" :disabled="refreshing" @click="refreshOverview">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M20 12a8 8 0 01-14.8 4.2M4 12A8 8 0 0118.8 7.8M18 4v4h-4M6 20v-4h4"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span>{{ refreshing ? '刷新中' : '刷新' }}</span>
          </button>
        </div>
      </template>
    </PageHero>

    <LoadingPanel v-if="pending && !data" title="正在加载站点概览" text="页面已经打开，正在读取统计数据…" />

    <div v-else-if="error" class="error-box">
      <h2>{{ error.data?.message || '加载失败' }}</h2>
      <button type="button" @click="refreshOverview">重试</button>
    </div>

    <div v-else-if="data" class="overview-grid">
      <section class="metric-grid" aria-label="站点总量">
        <article v-for="card in metricCards" :key="card.key" class="metric-card">
          <div class="metric-icon">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                :d="card.icon"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </div>
          <div class="metric-main">
            <span>{{ card.label }}</span>
            <strong>{{ numberText(card.value) }}</strong>
          </div>
        </article>
      </section>

      <section class="queue-panel">
        <header class="section-head">
          <div>
            <h2>处理通道</h2>
            <p>每 10 秒自动刷新。</p>
          </div>
        </header>

        <div class="queue-list">
          <article v-for="queue in data.queues" :key="queue.key" class="queue-row">
            <div class="queue-main">
              <strong>{{ queue.label }}</strong>
              <span>{{ queue.key }}</span>
            </div>
            <div class="queue-size">{{ numberText(queue.size) }}</div>
            <div class="queue-bar" aria-hidden="true">
              <span :style="{ width: `${queuePressure(queue.size)}%` }" />
            </div>
          </article>
        </div>
      </section>

      <section class="recent-panel">
        <header class="section-head">
          <div>
            <h2>最近保存任务</h2>
            <p>按爬取任务开始时间倒序。</p>
          </div>
        </header>

        <div class="recent-table">
          <div class="table-head table-row">
            <span>类型</span>
            <span>目标</span>
            <span>触发</span>
            <span>状态</span>
            <span>时间</span>
          </div>
          <div v-for="item in data.recent_tasks" :key="item.id" class="table-row">
            <span>{{ typeLabel(item.task_type) }}</span>
            <span class="target-id">{{ item.target }}</span>
            <span>{{ triggerLabel(item.trigger) }}</span>
            <span>
              <span class="status-chip" :data-status="item.status">{{ statusLabel(item.status) }}</span>
            </span>
            <span>{{ smart(item.started_at) }}</span>
          </div>
          <p v-if="!data.recent_tasks.length" class="empty">暂无爬取任务</p>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.overview-page {
  display: grid;
  gap: 18px;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.refresh-time {
  color: var(--text-muted);
  font-size: 13px;
}

.refresh-btn,
.error-box button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--hero-border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  padding: 5px 11px;
}

.refresh-btn:hover:not(:disabled),
.error-box button:hover {
  border-color: var(--link);
  color: var(--link);
}

.refresh-btn:disabled {
  cursor: wait;
  opacity: 0.65;
}

.refresh-btn svg {
  width: 15px;
  height: 15px;
}

.overview-grid {
  display: grid;
  gap: 16px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.metric-card,
.queue-panel,
.recent-panel,
.error-box {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 15px 16px;
}

.metric-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 7px;
  background: color-mix(in srgb, var(--link) 10%, transparent);
  color: var(--link);
  flex: 0 0 auto;
}

.metric-icon svg {
  width: 18px;
  height: 18px;
}

.metric-main {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.metric-main span {
  color: var(--text-muted);
  font-size: 13px;
}

.metric-main strong {
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text);
  font-size: 23px;
  line-height: 1.15;
  font-weight: 800;
}

.queue-panel,
.recent-panel {
  overflow: hidden;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 15px 18px 12px;
  border-bottom: 1px solid var(--border);
}

.section-head h2 {
  margin: 0;
  font-size: 17px;
  line-height: 1.3;
}

.section-head p {
  margin: 3px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.queue-list {
  display: grid;
}

.queue-row {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 100px minmax(240px, 42%);
  align-items: center;
  gap: 18px;
  padding: 14px 18px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
}

.queue-row:last-child {
  border-bottom: 0;
}

.queue-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.queue-main strong {
  font-size: 15px;
}

.queue-main span {
  color: var(--text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.queue-size {
  text-align: right;
  font-size: 22px;
  font-weight: 800;
}

.queue-bar {
  height: 8px;
  border-radius: 999px;
  background: var(--hover);
  overflow: hidden;
}

.queue-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--link), var(--lg-cyan));
}

.recent-table {
  display: grid;
}

.table-row {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr) 110px 110px 150px;
  align-items: center;
  gap: 14px;
  min-height: 42px;
  padding: 0 18px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
  font-size: 14px;
}

.table-row:last-child {
  border-bottom: 0;
}

.table-head {
  min-height: 36px;
  color: var(--text-muted);
  background: color-mix(in srgb, var(--hover) 70%, transparent);
  font-size: 12px;
  font-weight: 700;
}

.target-id {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 1px 8px;
  background: var(--hover);
  color: var(--text-muted);
  font-size: 12px;
}

.status-chip[data-status="success"] {
  color: var(--lg-green);
}

.status-chip[data-status="failed"],
.status-chip[data-status="rate_limited"] {
  color: var(--lg-red);
}
.status-chip[data-status="running"],
.status-chip[data-status="pending"] {
  color: var(--lg-yellow);
}

.status-chip[data-status="skipped"] {
  color: var(--text-muted);
}

.empty {
  margin: 0;
  padding: 22px 18px;
  color: var(--text-muted);
  text-align: center;
}

.error-box {
  padding: 30px;
  text-align: center;
}

.error-box h2 {
  margin: 0 0 12px;
  font-size: 18px;
}

@media (max-width: 1100px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .queue-row {
    grid-template-columns: minmax(0, 1fr) 86px;
  }

  .queue-bar {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }

  .table-row {
    grid-template-columns: 80px minmax(0, 1fr);
    gap: 6px 12px;
    padding: 9px 14px;
  }

  .table-row span:nth-child(3),
  .table-row span:nth-child(4),
  .table-row span:nth-child(5) {
    color: var(--text-muted);
    font-size: 12px;
  }
}
</style>


