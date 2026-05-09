<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const admin = useAdminStore()
const api = useAdminApi()

const logs = ref<any[]>([])
const offset = ref(0)
const limit = 50
const noMore = ref(false)
const loading = ref(false)

async function loadMore() {
  if (loading.value || noMore.value) return
  loading.value = true
  try {
    const rows = await api<any[]>('/admin/audit-logs', {
      query: { limit, offset: offset.value },
    })
    logs.value.push(...rows)
    if (rows.length < limit) noMore.value = true
    offset.value += rows.length
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (!admin.isLoggedIn) {
    navigateTo('/admin/login')
    return
  }
  loadMore()
})
</script>

<template>
  <div>
    <h1>管理操作审计日志</h1>

    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>时间</th>
          <th>管理员</th>
          <th>动作</th>
          <th>目标</th>
          <th>IP</th>
          <th>参数</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="l in logs" :key="l.id">
          <td>{{ l.id }}</td>
          <td class="small">{{ l.happened_at }}</td>
          <td>{{ l.admin }}</td>
          <td><code>{{ l.action }}</code></td>
          <td>
            <span v-if="l.target_type">{{ l.target_type }}/{{ l.target_id }}</span>
            <span v-else>-</span>
          </td>
          <td class="small">{{ l.ip }}</td>
          <td><code class="small">{{ l.params ? JSON.stringify(l.params) : '-' }}</code></td>
        </tr>
      </tbody>
    </table>

    <div class="more">
      <button v-if="!noMore" :disabled="loading" @click="loadMore">
        {{ loading ? '加载中...' : '加载更多' }}
      </button>
      <span v-else class="muted">没有更多了</span>
    </div>
  </div>
</template>

<style scoped>
table { width: 100%; border-collapse: collapse; margin-top: 16px; }
th, td {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}
.small { font-size: 13px; color: var(--text-muted); }
.more { text-align: center; padding: 20px; }
.muted { color: var(--text-muted); }
button {
  padding: 8px 20px;
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: 4px;
  cursor: pointer;
}
</style>
