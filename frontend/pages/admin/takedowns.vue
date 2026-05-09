<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const admin = useAdminStore()
const api = useAdminApi()

const status = ref<'pending' | 'all'>('pending')
const rows = ref<any[]>([])

async function load() {
  rows.value = await api('/admin/takedowns', { query: { status: status.value, limit: 100 } })
}

onMounted(() => {
  if (!admin.isLoggedIn) {
    navigateTo('/admin/login')
    return
  }
  load()
})

watch(status, load)

async function handle(id: number, action: 'approve' | 'reject') {
  const note = prompt(`${action === 'approve' ? '批准' : '拒绝'}的备注（可留空）：`) ?? ''
  await api(`/admin/takedowns/${id}/${action}`, {
    method: 'POST',
    body: { admin_note: note },
  })
  await load()
}
</script>

<template>
  <div>
    <h1>删除申请</h1>
    <div class="filter">
      状态：
      <select v-model="status">
        <option value="pending">待处理</option>
        <option value="all">全部</option>
      </select>
    </div>

    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>目标</th>
          <th>申请人</th>
          <th>理由</th>
          <th>状态</th>
          <th>提交</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.id }}</td>
          <td><code>{{ r.target_type }}/{{ r.target_id }}</code></td>
          <td>
            {{ r.requester_name || '-' }}<br>
            <small class="muted">{{ r.requester_contact || '' }}</small>
          </td>
          <td class="reason">{{ r.reason }}</td>
          <td>
            <span :class="`badge ${r.status}`">{{ r.status }}</span>
          </td>
          <td class="muted small">{{ r.created_at }}</td>
          <td>
            <button v-if="r.status === 'pending'" @click="handle(r.id, 'approve')" class="ok">批准</button>
            <button v-if="r.status === 'pending'" @click="handle(r.id, 'reject')" class="no">拒绝</button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="rows.length === 0" class="muted">暂无数据</p>
  </div>
</template>

<style scoped>
table { width: 100%; border-collapse: collapse; margin-top: 16px; }
th, td {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
th { background: var(--surface); }
.reason { max-width: 400px; }
.badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.badge.pending { background: #fff3cd; color: #8a6d00; }
.badge.approved { background: #d4edda; color: #155724; }
.badge.rejected { background: #f8d7da; color: #721c24; }
button.ok { background: var(--lg-green); color: white; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; }
button.no { background: var(--lg-red); color: white; border: none; padding: 4px 10px; border-radius: 4px; margin-left: 6px; cursor: pointer; }
.muted { color: var(--text-muted); }
.small { font-size: 13px; }
.filter { margin: 12px 0; }
</style>
