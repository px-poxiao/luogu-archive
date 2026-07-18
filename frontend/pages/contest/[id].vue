<script setup lang="ts">
const api = useApi()
const route = useRoute()
const contestId = computed(() => Number(route.params.id))
const page = ref(1)
const keyword = ref('')
const appliedKeyword = ref('')
const openWarningUid = ref<number | null>(null)

interface ContestProblem {
  pid: string
  label: string
  title: string
}

interface ScoreDetail {
  score?: number
  runningTime?: number
}

interface ScoreboardRow {
  uid: number
  name: string
  color: string
  avatar: string | null
  rank: number
  score: number
  running_time: number
  penalized: boolean
  problem_details: Record<string, ScoreDetail>
  rating: number | null
  delta: number | null
  rating_pending: boolean
  warnings: string[]
}

interface ScoreboardResponse {
  contest: {
    id: number
    name: string
    start_time: string
    end_time: string
    problem_count: number
    participant_count: number
    rated: boolean
    rating_mode: 'loading' | 'prediction' | 'official'
    status: string
  }
  problems: ContestProblem[]
  items: ScoreboardRow[]
  total: number
  page: number
  page_size: number
}

const { data, pending, error, refresh } = useLazyAsyncData(
  `contest-${contestId.value}`,
  () => api<ScoreboardResponse>(`/contest/${contestId.value}`, {
    query: { page: page.value, page_size: 50, q: appliedKeyword.value || undefined },
  }),
  { server: false, watch: [contestId, page, appliedKeyword] },
)

useHead(() => ({ title: data.value?.contest.name || '比赛' }))

const totalPages = computed(() => Math.max(1, Math.ceil((data.value?.total || 0) / 50)))
const ratingTitle = computed(() =>
  data.value?.contest.rating_mode === 'official' ? '等级分结果' : '等级分预估',
)

function search() {
  page.value = 1
  const next = keyword.value.trim()
  if (next === appliedKeyword.value) refresh()
  else appliedKeyword.value = next
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function formatDuration(milliseconds: number | undefined | null) {
  if (!milliseconds) return '-'
  const seconds = milliseconds / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 2 : 1)}s`
  const minutes = seconds / 60
  if (minutes < 60) return `${minutes.toFixed(2)}min`
  return `${(minutes / 60).toFixed(2)}h`
}

function formatScore(value: number | undefined) {
  if (value === undefined || value === null) return '-'
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function ratingColor(rating: number | null) {
  if (rating === null || rating < 800) return 'Gray'
  if (rating < 1200) return 'Orange'
  if (rating < 1500) return 'Green'
  if (rating < 1800) return 'Blue'
  if (rating < 2100) return 'Purple'
  if (rating < 2400) return 'Red'
  if (rating < 3000) return 'Black'
  return 'Cyan'
}

function toggleWarning(uid: number) {
  openWarningUid.value = openWarningUid.value === uid ? null : uid
}
</script>

<template>
  <div class="scoreboard-page" @click="openWarningUid = null">
    <LoadingPanel v-if="pending && !data" title="loading……" text="loading……" />

    <template v-else-if="data">
      <section class="contest-summary">
        <div class="contest-copy">
          <NuxtLink to="/contest" class="back-link">比赛 /</NuxtLink>
          <h1>{{ data.contest.name }}</h1>
          <p>{{ formatDate(data.contest.start_time) }} 至 {{ formatDate(data.contest.end_time) }}</p>
        </div>
        <dl class="contest-numbers">
          <div><dt>题数</dt><dd>{{ data.contest.problem_count }}</dd></div>
          <div><dt>参赛人数</dt><dd>{{ data.contest.participant_count }}</dd></div>
        </dl>
      </section>

      <section class="scoreboard-panel">
        <header class="scoreboard-toolbar">
          <div>
            <h2>排行榜</h2>
            <span v-if="data.contest.rating_mode === 'loading'" class="loading-state">loading……</span>
            <span v-else class="result-state">{{ data.contest.status }}</span>
          </div>
          <form class="search" @submit.prevent="search">
            <input v-model="keyword" placeholder="用户名或 UID" aria-label="搜索参赛者">
            <button type="submit">搜索</button>
          </form>
        </header>

        <div class="table-scroll">
          <table class="scoreboard-table">
            <thead>
              <tr>
                <th class="rank-col sticky-rank">名次</th>
                <th class="user-col sticky-user">参赛者</th>
                <th v-if="data.contest.rated" class="rating-col sticky-rating">{{ ratingTitle }}</th>
                <th class="total-col">总分</th>
                <th v-for="problem in data.problems" :key="problem.pid" class="problem-col">
                  <span
                    class="problem-tip"
                    tabindex="0"
                    :title="`${problem.pid} ${problem.title}`"
                  >
                    {{ problem.label }}
                    <span class="problem-popover">{{ problem.pid }} {{ problem.title }}</span>
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in data.items" :key="row.uid" :class="{ penalized: row.penalized }">
                <td class="rank-col sticky-rank">{{ row.penalized ? '-' : `#${row.rank}` }}</td>
                <td class="user-col sticky-user">
                  <LuoguUserName
                    :user="{ uid: row.uid, name: row.name, color: row.color, avatar: row.avatar, badge: null }"
                  />
                  <span class="uid">{{ row.uid }}</span>
                </td>
                <td v-if="data.contest.rated" class="rating-col sticky-rating">
                  <span v-if="row.rating_pending" class="rating-pending">loading……</span>
                  <span v-else-if="row.rating !== null" class="rating-value">
                    <span class="lg-name" :data-color="ratingColor(row.rating)">{{ row.rating }}</span>
                    <span v-if="(row.delta || 0) > 0" class="delta up">↑{{ row.delta }}</span>
                    <span v-else-if="(row.delta || 0) < 0" class="delta down">↓{{ Math.abs(row.delta || 0) }}</span>
                    <span v-else class="delta same">→0</span>
                  </span>
                  <span v-else class="rating-empty">-</span>
                  <span
                    v-if="row.warnings.length"
                    class="warning-wrap"
                    :class="{ active: openWarningUid === row.uid }"
                    @click.stop
                  >
                    <button
                      type="button"
                      class="warning-button"
                      aria-label="查看等级分说明"
                      :title="row.warnings.join('\n')"
                      @click="toggleWarning(row.uid)"
                    >!</button>
                    <span class="warning-popover">
                      <span v-for="reason in row.warnings" :key="reason">{{ reason }}</span>
                    </span>
                  </span>
                </td>
                <td class="total-col score-cell">
                  <strong>{{ row.penalized ? '-' : formatScore(row.score) }}</strong>
                  <small v-if="!row.penalized">{{ formatDuration(row.running_time) }}</small>
                </td>
                <td v-for="problem in data.problems" :key="problem.pid" class="problem-col score-cell">
                  <template v-if="row.problem_details[problem.pid]">
                    <strong :class="{ accepted: (row.problem_details[problem.pid].score || 0) > 0 }">
                      {{ formatScore(row.problem_details[problem.pid].score) }}
                    </strong>
                    <small>{{ formatDuration(row.problem_details[problem.pid].runningTime) }}</small>
                  </template>
                  <span v-else>-</span>
                </td>
              </tr>
              <tr v-if="!data.items.length">
                <td :colspan="4 + data.problems.length" class="empty">没有找到参赛者</td>
              </tr>
            </tbody>
          </table>
        </div>

        <nav v-if="totalPages > 1" class="pagination" aria-label="排行榜分页">
          <button :disabled="page <= 1" @click="page--">上一页</button>
          <span>第 {{ page }} / {{ totalPages }} 页</span>
          <button :disabled="page >= totalPages" @click="page++">下一页</button>
        </nav>
      </section>
    </template>

    <section v-else-if="error" class="load-error">比赛不存在或尚未完成归档</section>
  </div>
</template>

<style scoped>
.scoreboard-page { min-width: 0; }
.contest-summary {
  display: flex; justify-content: space-between; align-items: center; gap: 30px;
  min-height: 138px; box-sizing: border-box; padding: 26px 34px; margin-bottom: 26px;
  background: var(--hero-bg); border: 1px solid var(--hero-border); border-radius: 8px;
}
.contest-copy { min-width: 0; }
.back-link { display: inline-block; margin-bottom: 9px; color: var(--text-muted); font-size: 13px; }
.contest-copy h1 { margin: 0; font-size: 25px; line-height: 1.35; overflow-wrap: anywhere; }
.contest-copy p { margin: 9px 0 0; color: var(--text-muted); font-size: 13px; }
.contest-numbers { display: flex; gap: 30px; flex-shrink: 0; margin: 0; text-align: center; }
.contest-numbers div { min-width: 68px; }
.contest-numbers dt { color: var(--text-muted); font-size: 13px; }
.contest-numbers dd { margin: 2px 0 0; font-size: 20px; font-weight: 700; }
.scoreboard-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.scoreboard-toolbar {
  display: flex; justify-content: space-between; align-items: center; gap: 20px;
  min-height: 72px; padding: 0 24px; border-bottom: 1px solid var(--border);
}
.scoreboard-toolbar h2 { display: inline; margin: 0 10px 0 0; font-size: 18px; }
.loading-state, .result-state { color: var(--text-muted); font-size: 12px; }
.result-state { color: var(--lg-green); }
.search { display: flex; gap: 8px; }
.search input {
  width: 220px; min-width: 0; padding: 7px 9px; border: 1px solid var(--border);
  border-radius: 4px; background: var(--bg); color: var(--text); font: inherit;
}
.search button, .pagination button {
  border: 1px solid var(--border); border-radius: 4px; background: var(--surface);
  color: var(--text); padding: 7px 13px; cursor: pointer;
}
.table-scroll { overflow-x: auto; max-width: 100%; }
.scoreboard-table { width: 100%; min-width: max-content; border-collapse: separate; border-spacing: 0; }
th, td { height: 72px; box-sizing: border-box; padding: 10px 14px; border-bottom: 1px solid var(--border); text-align: center; white-space: nowrap; }
th { height: 54px; color: var(--text-muted); font-size: 13px; font-weight: 500; background: var(--surface); }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover td { background: var(--hover); }
.rank-col { width: 76px; min-width: 76px; color: var(--text-muted); }
.user-col { width: 220px; min-width: 220px; text-align: left; }
.rating-col { width: 150px; min-width: 150px; }
.total-col { width: 105px; min-width: 105px; }
.problem-col { width: 116px; min-width: 116px; }
.sticky-rank, .sticky-user, .sticky-rating { position: sticky; z-index: 2; background: var(--surface); }
.sticky-rank { left: 0; }
.sticky-user { left: 76px; }
.sticky-rating { left: 296px; box-shadow: 7px 0 10px -10px rgba(0, 0, 0, .7); }
thead .sticky-rank, thead .sticky-user, thead .sticky-rating { z-index: 4; }
.uid { display: block; margin-top: 2px; color: var(--text-muted); font-size: 11px; opacity: .7; }
.rating-value { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; }
.delta { font-size: 13px; }
.delta.up { color: var(--lg-green); }
.delta.down { color: var(--lg-red); }
.delta.same, .rating-pending, .rating-empty { color: var(--text-muted); }
.score-cell strong, .score-cell small { display: block; }
.score-cell small { margin-top: 1px; color: var(--text-muted); font-size: 11px; font-weight: 400; }
.score-cell .accepted { color: var(--lg-green); }
.penalized { opacity: .7; }
.problem-tip { position: relative; display: inline-flex; justify-content: center; min-width: 30px; cursor: help; }
.problem-popover, .warning-popover {
  position: absolute; z-index: 20; bottom: calc(100% + 9px); left: 50%; transform: translateX(-50%);
  display: none; min-width: 160px; max-width: 280px; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 5px; background: var(--surface); color: var(--text); box-shadow: 0 8px 22px rgba(0,0,0,.16);
  white-space: normal; text-align: left; font-size: 12px; line-height: 1.55;
}
.problem-tip:hover .problem-popover, .problem-tip:focus .problem-popover { display: block; }
.warning-wrap { position: relative; display: inline-flex; margin-left: 5px; vertical-align: middle; }
.warning-button {
  width: 18px; height: 18px; padding: 0; border: 1px solid var(--lg-orange); border-radius: 50%;
  background: transparent; color: var(--lg-orange); font-size: 12px; font-weight: 700; cursor: help;
}
.warning-popover { left: auto; right: -8px; transform: none; min-width: 220px; }
.warning-popover span { display: block; }
.warning-popover span + span { margin-top: 5px; padding-top: 5px; border-top: 1px solid var(--border); }
.warning-wrap:hover .warning-popover, .warning-wrap.active .warning-popover { display: block; }
.pagination { display: flex; justify-content: flex-end; align-items: center; gap: 12px; padding: 16px 22px; border-top: 1px solid var(--border); }
.pagination button:disabled { opacity: .45; cursor: default; }
.empty, .load-error { padding: 38px; text-align: center; color: var(--text-muted); }
@media (max-width: 768px) {
  .contest-summary {
    min-height: 0; align-items: stretch; flex-direction: column; gap: 16px;
    padding: 20px 18px;
  }
  .contest-copy h1 { font-size: 21px; }
  .contest-copy p { display: none; }
  .contest-numbers {
    justify-content: flex-start; gap: 24px; padding-top: 13px;
    border-top: 1px solid var(--hero-border); text-align: left;
  }
  .contest-numbers div { min-width: 54px; }
  .contest-numbers dd { font-size: 17px; }
  .scoreboard-toolbar { align-items: stretch; flex-direction: column; padding: 15px; }
  .search { width: 100%; }
  .search input { width: 100%; }
  .search button { flex-shrink: 0; white-space: nowrap; }
  .rank-col { width: 42px; min-width: 42px; padding-left: 3px; padding-right: 3px; }
  .user-col { width: 104px; min-width: 104px; padding-left: 6px; padding-right: 6px; overflow: hidden; text-overflow: ellipsis; }
  .rating-col { width: 100px; min-width: 100px; padding-left: 4px; padding-right: 4px; }
  .sticky-user { left: 42px; }
  .sticky-rating { left: 146px; }
  .rating-value { gap: 4px; }
  .warning-wrap { margin-left: 2px; }
  .warning-popover { position: fixed; left: 50%; right: auto; bottom: 24px; transform: translateX(-50%); width: min(280px, calc(100vw - 40px)); }
  .pagination { justify-content: center; }
}
</style>
