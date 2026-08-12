<script setup lang="ts">
import type { PluginSnapshot, PluginTag } from '~/types/plugin'

definePageMeta({ layout: 'admin' })
const admin = useAdminStore()
const api = useAdminApi()

const rows = ref<any[]>([])
const tags = ref<PluginTag[]>([])
const selected = ref<any>(null)
const snapshot = ref<PluginSnapshot | null>(null)
const status = ref('pending')
const applicationType = ref('')
const loading = ref(false)
const errorText = ref('')

const typeNames: Record<string, string> = {
  publish: '首次发布', update: '版本更新', recommend: '推荐申请', delete: '删除申请',
}
const statusNames: Record<string, string> = {
  pending: '待处理', approved: '已通过', rejected: '已拒绝', cancelled: '已撤销',
}

async function loadList() {
  rows.value = await api('/admin/plugin-applications', {
    query: { status: status.value, ...(applicationType.value ? { application_type: applicationType.value } : {}) },
  })
}

async function openApplication(id: number) {
  loading.value = true
  errorText.value = ''
  try {
    const data = await api<any>(`/admin/plugin-applications/${id}`)
    // 先复制普通响应对象，再放进 ref；Vue 的响应式 Proxy 不能直接 structuredClone。
    snapshot.value = Object.keys(data.snapshot || {}).length
      ? structuredClone(data.snapshot)
      : null
    selected.value = data
  } catch (error: any) {
    errorText.value = error?.data?.message || '申请详情加载失败'
  } finally {
    loading.value = false
  }
}

async function review(approved: boolean) {
  if (!selected.value) return
  const rejectionReason = approved ? null : prompt('请填写拒绝原因：')
  if (!approved && !rejectionReason) return
  if (approved && !confirm('确认按当前页面中的内容通过这条申请吗？')) return
  try {
    await api(`/admin/plugin-applications/${selected.value.id}/review`, {
      method: 'POST',
      body: {
        approved,
        rejection_reason: rejectionReason,
        snapshot: snapshot.value,
        admin_request_level: snapshot.value?.admin_request_level ?? null,
        admin_request_analysis: snapshot.value?.admin_request_analysis || null,
      },
    })
    selected.value = null
    snapshot.value = null
    await loadList()
  } catch (error: any) {
    errorText.value = error?.data?.message || '审核失败'
  }
}

onMounted(async () => {
  if (!admin.isLoggedIn) return navigateTo('/admin/login')
  ;[rows.value, tags.value] = await Promise.all([
    api('/admin/plugin-applications', { query: { status: status.value } }),
    api('/admin/plugin-tags'),
  ])
})

watch([status, applicationType], () => { void loadList() })
</script>

<template>
  <div class="admin-applications">
    <h1>插件申请</h1>
    <div class="filters">
      <select v-model="status">
        <option value="pending">待处理</option><option value="approved">已通过</option>
        <option value="rejected">已拒绝</option><option value="cancelled">已撤销</option><option value="all">全部</option>
      </select>
      <select v-model="applicationType">
        <option value="">全部类型</option><option value="publish">首次发布</option>
        <option value="update">版本更新</option><option value="recommend">推荐申请</option><option value="delete">删除申请</option>
      </select>
    </div>

    <div class="workspace">
      <aside class="application-list">
        <button v-for="row in rows" :key="row.id" type="button" :class="{ active: selected?.id === row.id }" @click="openApplication(row.id)">
          <strong>#{{ row.id }} · {{ typeNames[row.application_type] }}</strong>
          <span>文章 {{ row.article_id }}<template v-if="row.version"> · v{{ row.version }}</template></span>
          <small>{{ statusNames[row.status] || row.status }}</small>
        </button>
        <p v-if="!rows.length">暂无申请</p>
      </aside>

      <main class="review-pane">
        <p v-if="loading">loading……</p>
        <p v-else-if="!selected" class="empty">从左侧选择一条申请</p>
        <template v-else>
          <header class="review-head">
            <div>
              <h2>#{{ selected.id }} {{ typeNames[selected.application_type] }}</h2>
              <p>申请人：{{ selected.applicant?.display_name || '-' }} · 洛谷 UID {{ selected.applicant?.luogu_uid || '-' }}</p>
            </div>
            <NuxtLink :to="`/article/${selected.article_id}`" target="_blank">查看原文章</NuxtLink>
          </header>

          <p v-if="selected.reason" class="reason">申请理由：{{ selected.reason }}</p>
          <section v-if="snapshot && selected.current" class="diff">
            <h3>当前版与申请版</h3>
            <div><span>版本</span><del>{{ selected.current.version }}</del><ins>{{ snapshot.version }}</ins></div>
            <details>
              <summary>查看代码差异原文</summary>
              <div class="code-diff"><pre>{{ selected.current.code }}</pre><pre>{{ snapshot.code }}</pre></div>
            </details>
          </section>

          <PluginSnapshotForm v-if="snapshot" v-model="snapshot" :tags="tags" admin-fields />
          <div v-else class="reason-only">该申请不包含代码快照，请核对上方理由后处理。</div>

          <p v-if="errorText" class="error">{{ errorText }}</p>
          <footer v-if="selected.status === 'pending'" class="review-actions">
            <button type="button" class="reject" @click="review(false)">拒绝</button>
            <button type="button" class="approve" @click="review(true)">通过</button>
          </footer>
        </template>
      </main>
    </div>
  </div>
</template>

<style scoped>
h1 { margin-top: 0; }
.filters { display: flex; gap: 10px; margin-bottom: 15px; }
select { border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--text); padding: 7px 9px; }
.workspace { display: grid; grid-template-columns: 270px minmax(0, 1fr); min-height: 600px; border: 1px solid var(--border); }
.application-list { border-right: 1px solid var(--border); }
.application-list button { display: grid; width: 100%; gap: 4px; padding: 12px; border: 0; border-bottom: 1px solid var(--border); background: var(--surface); color: var(--text); text-align: left; cursor: pointer; }
.application-list button.active { background: var(--hover); box-shadow: inset 3px 0 var(--link); }
.application-list span, .application-list small { color: var(--text-muted); }
.application-list p { color: var(--text-muted); text-align: center; }
.review-pane { min-width: 0; padding: 20px; }
.review-head { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.review-head h2 { margin: 0; }
.review-head p { margin: 5px 0 0; color: var(--text-muted); }
.reason, .reason-only { padding: 11px 13px; border-left: 3px solid var(--lg-orange); background: var(--hover); }
.diff { margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }
.diff h3 { margin-top: 0; }
.diff > div { display: grid; grid-template-columns: 70px 1fr 1fr; gap: 12px; padding: 7px 0; }
.diff del, .diff ins { overflow-wrap: anywhere; }
.diff ins { color: var(--lg-green); text-decoration: none; }
.code-diff { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.code-diff pre { max-height: 260px; overflow: auto; margin: 0; padding: 10px; background: var(--hover); font-size: 11px; }
.review-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--border); }
.review-actions button { border: 0; border-radius: 5px; padding: 8px 18px; color: #fff; cursor: pointer; }
.reject { background: var(--lg-red); }.approve { background: var(--lg-green); }
.error { color: var(--lg-red); }.empty { color: var(--text-muted); text-align: center; padding: 80px 0; }
@media (max-width: 800px) { .workspace { grid-template-columns: 1fr; }.application-list { max-height: 300px; overflow: auto; border-right: 0; border-bottom: 1px solid var(--border); }.code-diff { grid-template-columns: 1fr; } }
</style>
