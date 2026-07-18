<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const admin = useAdminStore()
const api = useAdminApi()
const contestId = ref<number | null>(null)
const message = ref('')
const busy = ref('')

interface AdminContest {
  id: number
  name: string
  start_time: string
  end_time: string
  status: string
  rated: boolean
  participant_count: number
  error_message: string | null
}

interface AdminContestResponse {
  items: AdminContest[]
  total: number
}

const { data, refresh } = useLazyAsyncData(
  'admin-contests',
  () => api<AdminContestResponse>('/admin/contests'),
  { server: false },
)

const statusText: Record<string, string> = {
  discovered: '等待结束', queued: '已排队', crawling: '抓取榜单',
  refreshing_users: '刷新用户', predicted: '预测完成', official: '正式结果', failed: '失败',
}

async function runAction(key: string, path: string, options: any = {}) {
  if (busy.value) return
  busy.value = key
  message.value = 'loading……'
  try {
    const response = await api<{ message: string }>(path, { method: 'POST', ...options })
    message.value = response.message
    setTimeout(() => refresh(), 1000)
  } catch (error: any) {
    message.value = error?.data?.message || '操作失败'
  } finally {
    busy.value = ''
  }
}

function archiveById() {
  if (!contestId.value) return
  runAction('archive-new', '/admin/contests/archive', { body: { contest_id: contestId.value } })
}

onMounted(() => {
  if (!admin.isLoggedIn) navigateTo('/admin/login')
})
</script>

<template>
  <div>
    <h1>比赛归档</h1>
    <p class="note">自动任务每小时扫描比赛列表第一页，比赛结束后只归档一次榜单。</p>

    <section class="actions">
      <button :disabled="!!busy" @click="runAction('discover', '/admin/contests/discover')">立即扫描第一页</button>
      <form @submit.prevent="archiveById">
        <input v-model.number="contestId" type="number" min="1" placeholder="比赛 ID">
        <button :disabled="!!busy || !contestId" type="submit">立即归档</button>
      </form>
      <span v-if="message" class="message">{{ message }}</span>
    </section>

    <section class="table-wrap">
      <table>
        <thead><tr><th>比赛</th><th>人数</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in data?.items || []" :key="item.id">
            <td><strong>{{ item.name }}</strong><small>#{{ item.id }}</small></td>
            <td>{{ item.participant_count }}</td>
            <td>
              {{ statusText[item.status] || item.status }}
              <small v-if="item.error_message" class="error">{{ item.error_message }}</small>
            </td>
            <td class="row-actions">
              <button :disabled="!!busy" @click="runAction(`archive-${item.id}`, '/admin/contests/archive', { body: { contest_id: item.id } })">重新归档</button>
              <button v-if="item.rated" :disabled="!!busy" @click="runAction(`calc-${item.id}`, `/admin/contests/${item.id}/recalculate`)">重新计算</button>
              <button v-if="item.rated && item.status !== 'official'" :disabled="!!busy" @click="runAction(`check-${item.id}`, `/admin/contests/${item.id}/check-official`)">检查正式结果</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.note { color: var(--text-muted); }
.actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
.actions form { display: flex; gap: 8px; }
input { width: 140px; padding: 7px 9px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text); }
button { padding: 7px 12px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text); cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
.message { color: var(--text-muted); font-size: 13px; }
.table-wrap { overflow-x: auto; border: 1px solid var(--border); background: var(--surface); }
table { width: 100%; min-width: 820px; border-collapse: collapse; }
th, td { padding: 11px 13px; border-bottom: 1px solid var(--border); text-align: left; }
th { color: var(--text-muted); font-size: 13px; }
td small { display: block; color: var(--text-muted); }
.error { color: var(--lg-red); white-space: normal; max-width: 360px; }
.row-actions { display: flex; gap: 7px; }
</style>
