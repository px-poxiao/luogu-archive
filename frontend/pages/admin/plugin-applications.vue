<script setup lang="ts">
import type { PluginSnapshot, PluginTag } from '~/types/plugin'

definePageMeta({ layout: 'admin' })
const admin = useAdminStore()
const api = useAdminApi()
const { render } = useMarkdown()
const { runtimeMode } = usePluginLabels()

const rows = ref<any[]>([])
const tags = ref<PluginTag[]>([])
const selected = ref<any>(null)
const snapshot = ref<PluginSnapshot | null>(null)
const status = ref('pending')
const applicationType = ref('')
const loading = ref(false)
const errorText = ref('')
const currentCodePreview = computed(() => ({
  code: selected.value?.current?.code || '',
  truncated: selected.value?.current?.code_truncated ?? false,
}))
const submittedCodePreview = computed(() => ({
  code: snapshot.value?.code || '',
  truncated: snapshot.value?.code_truncated ?? false,
}))
const userAnalysisHtml = computed(() => render(snapshot.value?.user_request_analysis || ''))
const submittedTags = computed(() => {
  const selectedIds = new Set(snapshot.value?.tag_ids || [])
  return tags.value.filter(tag => selectedIds.has(tag.id))
})
const adminAnalysis = computed({
  get: () => snapshot.value?.admin_request_analysis || '',
  set: (value: string) => {
    if (snapshot.value) snapshot.value.admin_request_analysis = value || null
  },
})
const adminLevelEnabled = computed({
  get: () => snapshot.value?.admin_request_level !== null && snapshot.value?.admin_request_level !== undefined,
  set: (enabled: boolean) => {
    if (!snapshot.value) return
    snapshot.value.admin_request_level = enabled ? snapshot.value.user_request_level : null
  },
})

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

async function downloadSubmittedCode() {
  if (!snapshot.value || !selected.value) return
  const blob = await api<Blob>(`/admin/plugin-applications/${selected.value.id}/download`, {
    responseType: 'blob',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = (snapshot.value.download_filename || 'plugin.user.js')
    .split(/[\\/]/).pop() || 'plugin.user.js'
  anchor.click()
  URL.revokeObjectURL(url)
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
          <section v-if="snapshot" class="readonly-submission">
            <div class="section-title">
              <h3>用户提交内容</h3>
              <span>只读</span>
            </div>
            <dl>
              <div><dt>介绍</dt><dd>{{ snapshot.summary || '留空，由系统从文章正文生成' }}</dd></div>
              <div><dt>代码版本</dt><dd>{{ snapshot.version }}</dd></div>
              <div><dt>下载文件名</dt><dd>{{ snapshot.download_filename }}</dd></div>
              <div><dt>运行方式</dt><dd>{{ runtimeMode(snapshot.runtime_mode) }}</dd></div>
              <div><dt>兼容设备</dt><dd>{{ [snapshot.supports_desktop ? '桌面端' : '', snapshot.supports_mobile ? '移动端' : ''].filter(Boolean).join('、') || '-' }}</dd></div>
              <div><dt>最后验证</dt><dd>{{ snapshot.last_verified_on }}</dd></div>
              <div class="wide"><dt>功能标签</dt><dd>{{ submittedTags.map(tag => tag.name).join('、') || '未选择' }}</dd></div>
            </dl>
          </section>

          <section v-if="snapshot && selected.current" class="diff">
            <div class="section-title">
              <h3>当前版与申请版</h3>
              <button type="button" @click="downloadSubmittedCode">下载申请版完整代码</button>
            </div>
            <div class="version-diff"><span>版本</span><del>{{ selected.current.version }}</del><ins>{{ snapshot.version }}</ins></div>
            <details>
              <summary>查看代码差异原文</summary>
              <div class="code-diff">
                <div>
                  <strong>当前正式版</strong>
                  <p v-if="currentCodePreview.truncated">预览已截断，完整代码未被修改。</p>
                  <pre>{{ currentCodePreview.code }}</pre>
                </div>
                <div>
                  <strong>本次申请版</strong>
                  <p v-if="submittedCodePreview.truncated">预览已截断，完整代码未被修改。</p>
                  <pre>{{ submittedCodePreview.code }}</pre>
                </div>
              </div>
            </details>
          </section>

          <section v-else-if="snapshot" class="submitted-code">
            <div class="section-title">
              <h3>代码预览</h3>
              <button type="button" @click="downloadSubmittedCode">下载完整代码</button>
            </div>
            <p v-if="submittedCodePreview.truncated" class="preview-limit">预览最多显示 1000 行且不超过 50 KiB，完整代码未被修改。</p>
            <pre>{{ submittedCodePreview.code }}</pre>
          </section>

          <template v-if="snapshot">
            <section class="user-request readonly-submission">
              <div class="section-title"><h3>用户请求说明</h3><span>只读</span></div>
              <PluginRequestLevelBadge :level="snapshot.user_request_level" />
              <div class="lg-content analysis-content" v-html="userAnalysisHtml" />
            </section>

            <section class="admin-evaluation">
              <h3>管理员评估</h3>
              <label class="admin-level-toggle">
                <input v-model="adminLevelEnabled" type="checkbox">
                <span>调整公开显示的请求等级</span>
              </label>
              <div v-if="adminLevelEnabled" class="level-editor">
                <div>
                  <span>管理员显示等级</span>
                  <PluginRequestLevelBadge :level="snapshot.admin_request_level ?? snapshot.user_request_level" />
                </div>
                <input v-model.number="snapshot.admin_request_level" type="range" min="0" max="3" step="1">
              </div>
              <PluginMarkdownEditor
                v-model="adminAnalysis"
                label="管理组请求分析"
                :maxlength="20000"
                placeholder="管理组人工审核结论（可留空）"
              />
            </section>
          </template>
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
.readonly-submission, .submitted-code, .admin-evaluation { margin-bottom: 24px; padding: 16px; border: 1px solid var(--border); background: var(--surface); }
.section-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 13px; }
.section-title h3 { margin: 0; }
.section-title > span { color: var(--text-muted); font-size: 12px; }
.section-title button { border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--text); padding: 6px 10px; cursor: pointer; }
.readonly-submission dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 18px; margin: 0; }
.readonly-submission dl > div { min-width: 0; }
.readonly-submission dl .wide { grid-column: 1 / -1; }
.readonly-submission dt { color: var(--text-muted); font-size: 12px; }
.readonly-submission dd { margin: 3px 0 0; overflow-wrap: anywhere; }
.diff { margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }
.diff h3 { margin: 0; }
.version-diff { display: grid; grid-template-columns: 70px 1fr 1fr; gap: 12px; padding: 7px 0; }
.diff del, .diff ins { overflow-wrap: anywhere; }
.diff ins { color: var(--lg-green); text-decoration: none; }
.code-diff { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.code-diff > div { min-width: 0; }
.code-diff strong { display: block; margin-bottom: 6px; font-size: 13px; }
.code-diff p { margin: 0 0 6px; padding: 7px 9px; border-left: 3px solid var(--lg-yellow); background: color-mix(in srgb, var(--lg-yellow) 10%, var(--surface)); color: var(--text-muted); font-size: 12px; }
.code-diff pre { max-height: 260px; overflow: auto; margin: 0; padding: 10px; background: var(--hover); font-size: 11px; }
.submitted-code pre { max-height: 360px; overflow: auto; margin: 0; padding: 12px; background: var(--hover); font-size: 12px; white-space: pre; }
.preview-limit { margin: 0 0 8px; padding: 8px 10px; border-left: 3px solid var(--lg-yellow); background: color-mix(in srgb, var(--lg-yellow) 10%, var(--surface)); color: var(--text-muted); font-size: 12px; }
.user-request { display: grid; justify-items: start; gap: 13px; }
.analysis-content { width: 100%; }
.admin-evaluation { display: grid; gap: 15px; }
.admin-evaluation h3 { margin: 0; }
.admin-level-toggle { display: inline-flex; align-items: center; gap: 8px; justify-self: start; }
.level-editor { display: grid; gap: 9px; padding: 12px; border: 1px solid var(--border); }
.level-editor > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.level-editor input { width: 100%; accent-color: var(--link); }
.review-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--border); }
.review-actions button { border: 0; border-radius: 5px; padding: 8px 18px; color: #fff; cursor: pointer; }
.reject { background: var(--lg-red); }.approve { background: var(--lg-green); }
.error { color: var(--lg-red); }.empty { color: var(--text-muted); text-align: center; padding: 80px 0; }
@media (max-width: 800px) { .workspace { grid-template-columns: 1fr; }.application-list { max-height: 300px; overflow: auto; border-right: 0; border-bottom: 1px solid var(--border); }.code-diff, .readonly-submission dl { grid-template-columns: 1fr; }.readonly-submission dl .wide { grid-column: auto; } }
</style>
