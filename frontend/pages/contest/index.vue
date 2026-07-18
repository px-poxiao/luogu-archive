<script setup lang="ts">
const api = useApi()
const page = ref(1)
const keyword = ref('')
const appliedKeyword = ref('')

interface ContestItem {
  id: number
  name: string
  start_time: string
  end_time: string
  problem_count: number
  participant_count: number
  rated: boolean
  status: string
}

interface ContestListResponse {
  items: ContestItem[]
  total: number
  page: number
  page_size: number
}

const { data, pending, refresh } = useLazyAsyncData(
  'contest-list',
  () => api<ContestListResponse>('/contests', {
    query: { page: page.value, page_size: 20, q: appliedKeyword.value || undefined },
  }),
  { server: false, watch: [page, appliedKeyword] },
)

const totalPages = computed(() => Math.max(1, Math.ceil((data.value?.total || 0) / 20)))

function search() {
  page.value = 1
  appliedKeyword.value = keyword.value.trim()
  if (appliedKeyword.value === keyword.value.trim()) refresh()
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <div class="contest-list-page">
    <section class="contest-heading">
      <div>
        <h1>比赛</h1>
        <p>已结束比赛的排行榜与等级分结果</p>
      </div>
      <form class="search" @submit.prevent="search">
        <input v-model="keyword" placeholder="比赛名称或 ID" aria-label="搜索比赛">
        <button type="submit">搜索</button>
      </form>
    </section>

    <LoadingPanel v-if="pending && !data" title="loading……" text="loading……" />
    <section v-else class="contest-table-wrap">
      <table class="contest-table">
        <thead>
          <tr><th>比赛</th><th>结束时间</th><th>题数</th><th>参赛人数</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in data?.items || []" :key="item.id">
            <td>
              <NuxtLink :to="`/contest/${item.id}`" class="contest-name">{{ item.name }}</NuxtLink>
              <span class="contest-id">#{{ item.id }}</span>
            </td>
            <td>{{ formatTime(item.end_time) }}</td>
            <td>{{ item.problem_count }}</td>
            <td>{{ item.participant_count }}</td>
            <td><span class="status" :class="{ official: item.status === '正式结果' }">{{ item.status }}</span></td>
          </tr>
          <tr v-if="!data?.items.length"><td colspan="5" class="empty">没有找到比赛</td></tr>
        </tbody>
      </table>
    </section>

    <nav v-if="totalPages > 1" class="pagination" aria-label="比赛列表分页">
      <button :disabled="page <= 1" @click="page--">上一页</button>
      <span>{{ page }} / {{ totalPages }}</span>
      <button :disabled="page >= totalPages" @click="page++">下一页</button>
    </nav>
  </div>
</template>

<style scoped>
.contest-list-page { min-width: 0; }
.contest-heading {
  display: flex; align-items: end; justify-content: space-between; gap: 24px;
  padding: 24px 28px; margin-bottom: 20px; border: 1px solid var(--hero-border);
  background: var(--hero-bg); border-radius: 8px;
}
.contest-heading h1 { margin: 0; font-size: 26px; }
.contest-heading p { margin: 5px 0 0; color: var(--text-muted); font-size: 14px; }
.search { display: flex; gap: 8px; }
.search input {
  width: 240px; min-width: 0; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 5px; background: var(--surface); color: var(--text); font: inherit;
}
.search button, .pagination button {
  border: 1px solid var(--border); border-radius: 5px; background: var(--surface);
  color: var(--text); padding: 8px 14px; cursor: pointer;
}
.contest-table-wrap { overflow-x: auto; border: 1px solid var(--border); background: var(--surface); }
.contest-table { width: 100%; min-width: 760px; border-collapse: collapse; }
th, td { padding: 13px 16px; border-bottom: 1px solid var(--border); text-align: left; }
th { color: var(--text-muted); font-size: 13px; font-weight: 600; }
.contest-name { color: var(--text); font-weight: 600; }
.contest-id { margin-left: 8px; color: var(--text-muted); font-size: 12px; }
.status { color: var(--lg-orange); }
.status.official { color: var(--lg-green); }
.empty { text-align: center; color: var(--text-muted); padding: 36px; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 14px; margin-top: 20px; }
.pagination button:disabled { opacity: .45; cursor: default; }
@media (max-width: 768px) {
  .contest-heading { align-items: stretch; flex-direction: column; padding: 18px 16px; }
  .search input { width: 100%; }
  .search { width: 100%; }
}
</style>
