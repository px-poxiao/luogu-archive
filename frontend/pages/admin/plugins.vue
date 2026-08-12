<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const admin = useAdminStore()
const api = useAdminApi()
const { render } = useMarkdown()

const rows = ref<any[]>([])
const managing = ref<any>(null)
const message = ref('')

const userAnalysisHtml = computed(() => render(managing.value?.user_request_analysis || ''))
const adminAnalysis = computed({
  get: () => managing.value?.admin_request_analysis || '',
  set: (value: string) => {
    if (managing.value) managing.value.admin_request_analysis = value || null
  },
})
const adminLevelEnabled = computed({
  get: () => managing.value?.admin_request_level !== null && managing.value?.admin_request_level !== undefined,
  set: (enabled: boolean) => {
    if (!managing.value) return
    managing.value.admin_request_level = enabled ? managing.value.user_request_level : null
  },
})

async function load() {
  rows.value = await api('/admin/plugins')
}

function beginManage(row: any) {
  // 表格行是 Vue Proxy，管理表单只操作普通副本。
  managing.value = structuredClone(toRaw(row))
  message.value = ''
}

async function saveManagement() {
  if (!managing.value) return
  await Promise.all([
    api(`/admin/plugins/${managing.value.id}`, {
      method: 'PUT',
      body: {
        is_official: managing.value.is_official,
        is_recommended: managing.value.is_recommended,
      },
    }),
    api(`/admin/plugins/${managing.value.id}/evaluation`, {
      method: 'PUT',
      body: {
        admin_request_level: managing.value.admin_request_level ?? null,
        admin_request_analysis: managing.value.admin_request_analysis || null,
      },
    }),
  ])
  const pluginId = managing.value.id
  message.value = '管理状态与请求评估已更新'
  await load()
  const refreshed = rows.value.find(row => row.id === pluginId)
  managing.value = refreshed ? structuredClone(toRaw(refreshed)) : null
}

async function changeListed(row: any) {
  if (row.is_listed) {
    const reason = prompt('请填写下架原因：')
    if (!reason) return
    await api(`/admin/plugins/${row.id}/unlist`, { method: 'POST', body: { reason } })
  } else {
    await api(`/admin/plugins/${row.id}/restore`, { method: 'POST' })
  }
  await load()
  if (managing.value?.id === row.id) managing.value = null
}

onMounted(async () => {
  if (!admin.isLoggedIn) return navigateTo('/admin/login')
  await load()
})
</script>

<template>
  <div>
    <h1>插件管理</h1>
    <p v-if="message" class="message">{{ message }}</p>
    <div class="workspace">
      <div class="plugin-table">
        <table>
          <thead><tr><th>插件</th><th>状态</th><th>徽章</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td><strong>{{ row.name }}</strong><br><small>{{ row.article_id }}</small></td>
              <td>{{ row.is_listed ? '公开' : '已下架' }}</td>
              <td>{{ [row.is_official ? '官方' : '', row.is_recommended ? '推荐' : ''].filter(Boolean).join('、') || '-' }}</td>
              <td>
                <button type="button" @click="beginManage(row)">管理</button>
                <button type="button" @click="changeListed(row)">{{ row.is_listed ? '下架' : '恢复' }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <section v-if="managing" class="manage-pane">
        <header>
          <div>
            <h2>{{ managing.name }}</h2>
            <span>文章 {{ managing.article_id }}</span>
          </div>
          <NuxtLink :to="`/plugin/${managing.article_id}`" target="_blank">查看插件</NuxtLink>
        </header>

        <section class="readonly-block">
          <div class="section-title"><h3>用户提交内容</h3><span>只读</span></div>
          <dl>
            <div class="wide"><dt>介绍</dt><dd>{{ managing.summary || '-' }}</dd></div>
            <div class="wide"><dt>功能标签</dt><dd>{{ managing.tags.map((tag: any) => tag.name).join('、') || '未选择' }}</dd></div>
          </dl>
        </section>

        <section class="readonly-block user-request">
          <div class="section-title"><h3>用户请求说明</h3><span>只读</span></div>
          <PluginRequestLevelBadge :level="managing.user_request_level" />
          <div class="lg-content analysis-content" v-html="userAnalysisHtml" />
        </section>

        <section class="admin-controls">
          <h3>管理状态</h3>
          <div class="choice-row">
            <label><input v-model="managing.is_official" type="checkbox">官方插件</label>
            <label><input v-model="managing.is_recommended" type="checkbox">推荐插件</label>
          </div>
        </section>

        <section class="admin-controls">
          <h3>管理员请求评估</h3>
          <label class="level-toggle">
            <input v-model="adminLevelEnabled" type="checkbox">
            调整公开显示的请求等级
          </label>
          <div v-if="adminLevelEnabled" class="level-editor">
            <div>
              <span>管理员显示等级</span>
              <PluginRequestLevelBadge :level="managing.admin_request_level ?? managing.user_request_level" />
            </div>
            <input v-model.number="managing.admin_request_level" type="range" min="0" max="3" step="1">
          </div>
          <PluginMarkdownEditor
            v-model="adminAnalysis"
            label="管理组请求分析"
            :maxlength="20000"
            placeholder="管理组人工审核结论（可留空）"
          />
        </section>

        <button type="button" class="save" @click="saveManagement">保存管理信息</button>
      </section>
    </div>
  </div>
</template>

<style scoped>
h1 { margin-top: 0; }
.workspace { display: grid; grid-template-columns: minmax(420px, .9fr) minmax(0, 1.1fr); gap: 20px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 9px; border-bottom: 1px solid var(--border); text-align: left; }
th { background: var(--surface); }
td button { margin-right: 6px; }
button { border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--text); padding: 6px 10px; cursor: pointer; }
.manage-pane { display: grid; gap: 18px; min-width: 0; padding: 18px; border: 1px solid var(--border); }
.manage-pane > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.manage-pane h2, .manage-pane h3 { margin: 0; }
.manage-pane header span, small { color: var(--text-muted); }
.readonly-block, .admin-controls { display: grid; gap: 13px; padding: 15px; border: 1px solid var(--border); background: var(--surface); }
.section-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-title > span { color: var(--text-muted); font-size: 12px; }
dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 18px; margin: 0; }
dl .wide { grid-column: 1 / -1; }
dt { color: var(--text-muted); font-size: 12px; }
dd { margin: 3px 0 0; overflow-wrap: anywhere; }
.user-request { justify-items: start; }
.analysis-content { width: 100%; }
.choice-row { display: flex; flex-wrap: wrap; gap: 12px 20px; }
.choice-row label, .level-toggle { display: inline-flex; align-items: center; gap: 7px; }
.level-editor { display: grid; gap: 10px; padding: 12px; border: 1px solid var(--border); }
.level-editor > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.level-editor input { width: 100%; accent-color: var(--link); }
.save { justify-self: end; border-color: var(--link); background: var(--link); color: #fff; padding: 8px 15px; }
.message { padding: 8px 12px; border-left: 3px solid var(--lg-green); }
@media (max-width: 900px) {
  .workspace { grid-template-columns: 1fr; }
  dl { grid-template-columns: 1fr; }
  dl .wide { grid-column: auto; }
}
</style>
