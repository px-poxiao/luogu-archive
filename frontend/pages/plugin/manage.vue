<script setup lang="ts">
const auth = useAuthStore()
const api = useApi()
const loading = ref(true)
const errorText = ref('')
const data = ref<{ plugins: any[]; applications: any[] }>({ plugins: [], applications: [] })

const typeNames: Record<string, string> = {
  publish: '首次发布', update: '版本更新', recommend: '推荐申请', delete: '删除申请',
}
const statusNames: Record<string, string> = {
  pending: '待审核', approved: '已通过', rejected: '已拒绝', cancelled: '已撤销',
}

async function load() {
  loading.value = true
  try {
    data.value = await api('/plugins/manage')
  } catch (error: any) {
    errorText.value = error?.data?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function cancel(applicationId: number) {
  if (!confirm('确定撤销这条待审核申请吗？')) return
  await api(`/plugins/applications/${applicationId}`, { method: 'DELETE' })
  await load()
}

async function reasonAction(articleId: string, type: 'recommend' | 'delete') {
  const reason = prompt(type === 'recommend' ? '请填写推荐理由：' : '请填写删除原因：')
  if (!reason) return
  try {
    await api(`/plugins/${articleId}/applications/${type}`, { method: 'POST', body: { reason } })
    await load()
  } catch (error: any) {
    alert(error?.data?.message || '提交失败')
  }
}

onMounted(async () => {
  if (!auth.initialized) await auth.tryRefresh()
  if (!auth.isLoggedIn) {
    await navigateTo('/login?redirect=/plugin/manage')
    return
  }
  await load()
})

useHead({ title: '我的插件 - 洛谷档案馆' })
</script>

<template>
  <div class="manage-page">
    <header class="manage-head">
      <div><h1>我的插件</h1><p>查看公开插件、待审核版本和历史申请。</p></div>
      <NuxtLink to="/plugin/submit">提交新插件</NuxtLink>
    </header>
    <LoadingPanel v-if="loading" title="loading……" text="" />
    <p v-else-if="errorText" class="error">{{ errorText }}</p>
    <template v-else>
      <section>
        <h2>已发布插件</h2>
        <div v-if="data.plugins.length" class="plugin-list">
          <article v-for="plugin in data.plugins" :key="plugin.id" class="plugin-row">
            <div>
              <h3><NuxtLink :to="`/plugin/${plugin.article_id}`">{{ plugin.name }}</NuxtLink></h3>
              <p>文章 {{ plugin.article_id }} · {{ plugin.is_listed ? '公开展示' : '已下架' }}</p>
            </div>
            <div class="row-actions">
              <NuxtLink :to="`/plugin/submit?article_id=${plugin.article_id}`">提交更新</NuxtLink>
              <button v-if="!plugin.is_recommended" type="button" @click="reasonAction(plugin.article_id, 'recommend')">申请推荐</button>
              <button type="button" class="danger" @click="reasonAction(plugin.article_id, 'delete')">申请删除</button>
            </div>
          </article>
        </div>
        <p v-else class="empty">还没有通过审核的插件</p>
      </section>

      <section>
        <h2>申请记录</h2>
        <div v-if="data.applications.length" class="applications">
          <article v-for="application in data.applications" :key="application.id" class="application-row">
            <div>
              <strong>{{ typeNames[application.application_type] || application.application_type }}</strong>
              <span>文章 {{ application.article_id }}<template v-if="application.version"> · v{{ application.version }}</template></span>
            </div>
            <div class="application-status">
              <span :class="`status ${application.status}`">{{ statusNames[application.status] || application.status }}</span>
              <button v-if="application.status === 'pending'" type="button" @click="cancel(application.id)">撤销</button>
            </div>
            <p v-if="application.review_note" class="review-note">审核意见：{{ application.review_note }}</p>
          </article>
        </div>
        <p v-else class="empty">暂无申请记录</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.manage-page { display: grid; gap: 26px; }
.manage-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 22px 26px; border: 1px solid var(--hero-border); border-radius: 8px; background: var(--hero-bg); }
.manage-head h1 { margin: 0; font-size: 27px; }
.manage-head p { margin: 6px 0 0; color: var(--text-muted); }
.manage-head > a { padding: 8px 14px; border-radius: 6px; background: var(--link); color: #fff; text-decoration: none; }
section > h2 { margin: 0 0 12px; font-size: 20px; }
.plugin-list, .applications { border-top: 1px solid var(--border); }
.plugin-row, .application-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px 20px; padding: 15px 2px; border-bottom: 1px solid var(--border); }
.plugin-row h3 { margin: 0; font-size: 17px; }
.plugin-row p, .application-row span { margin: 4px 0 0; color: var(--text-muted); font-size: 13px; }
.row-actions, .application-status { display: flex; align-items: center; gap: 9px; }
.row-actions a, .row-actions button, .application-status button { border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--text); padding: 6px 9px; text-decoration: none; cursor: pointer; font: inherit; font-size: 13px; }
.row-actions .danger { color: var(--lg-red); }
.status { padding: 2px 8px; border-radius: 4px; }
.status.pending { background: #fff3cd; color: #7a5d00; }
.status.approved { background: #d8f3df; color: #17652d; }
.status.rejected { background: #ffe0e0; color: #9f1c24; }
.status.cancelled { background: var(--hover); }
.review-note { grid-column: 1 / -1; margin: 0; color: var(--lg-red); font-size: 13px; }
.empty { padding: 28px 0; color: var(--text-muted); text-align: center; border-top: 1px solid var(--border); }
.error { color: var(--lg-red); }
@media (max-width: 720px) {
  .manage-head { align-items: flex-start; flex-direction: column; }
  .plugin-row, .application-row { grid-template-columns: 1fr; }
  .row-actions { flex-wrap: wrap; }
}
</style>
