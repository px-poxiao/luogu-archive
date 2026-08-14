<script setup lang="ts">
import type { PluginDetail, PluginSnapshot, PluginVersion } from '~/types/plugin'
import { PLUGIN_CODE_COPY_MAX_BYTES } from '~/utils/pluginCode'

const route = useRoute()
const articleId = String(route.params.article_id)
const auth = useAuthStore()
const api = useApi()
const { render } = useMarkdown()
const { format } = useTime()
const { runtimeMode } = usePluginLabels()

const loading = ref(true)
const errorText = ref('')
const detail = ref<PluginDetail | null>(null)
const article = ref<any>(null)
const selectedVersion = ref<PluginVersion | null>(null)
const showPending = ref(false)
const activeTab = ref<'article' | 'code' | 'analysis'>('article')
const articleRef = ref<HTMLElement | null>(null)
const action = ref<'copy' | 'download'>('copy')
const confirmOpen = ref(false)
const toast = ref('')
const reportOpen = ref(false)
const reportType = ref('dangerous_request')
const reportDescription = ref('')
useCopyCode(articleRef)

const pendingSnapshot = computed(() => detail.value?.pending_application?.snapshot || null)
const displaySnapshot = computed<PluginSnapshot | null>(() => showPending.value ? pendingSnapshot.value : null)
const displayName = computed(() => article.value?.title || detail.value?.name || '插件')
const displayTags = computed(() => showPending.value
  ? detail.value?.pending_application?.tags || []
  : detail.value?.tags || [])
const articleHtml = computed(() => article.value ? render(article.value.content_md) : '')

const displayVersion = computed<PluginVersion | null>(() => {
  if (!displaySnapshot.value) return selectedVersion.value
  const snapshot = displaySnapshot.value
  return {
    id: 0,
    version: snapshot.version,
    code: snapshot.code,
    code_bytes: snapshot.code_bytes ?? new TextEncoder().encode(snapshot.code).length,
    code_truncated: snapshot.code_truncated ?? false,
    code_sha256: '审核通过后由后端计算',
    download_filename: snapshot.download_filename,
    user_request_level: snapshot.user_request_level,
    user_request_analysis: snapshot.user_request_analysis,
    admin_request_level: null,
    admin_request_analysis: null,
    final_request_level: snapshot.user_request_level,
    runtime_mode: snapshot.runtime_mode,
    supports_desktop: snapshot.supports_desktop,
    supports_mobile: snapshot.supports_mobile,
    last_verified_on: snapshot.last_verified_on,
    published_at: '',
  }
})

const codePreview = computed(() => ({
  code: displayVersion.value?.code || '',
  truncated: displayVersion.value?.code_truncated ?? false,
}))
const copyDisabled = computed(() => (displayVersion.value?.code_bytes ?? 0) > PLUGIN_CODE_COPY_MAX_BYTES)

const userAnalysisHtml = computed(() => render(displayVersion.value?.user_request_analysis || ''))
const adminAnalysisHtml = computed(() => render(displayVersion.value?.admin_request_analysis || ''))

async function load() {
  loading.value = true
  errorText.value = ''
  try {
    const [pluginData, articleData] = await Promise.all([
      api<PluginDetail>(`/plugins/${articleId}`),
      api<any>(`/article/${articleId}`),
    ])
    detail.value = pluginData
    article.value = articleData
    selectedVersion.value = pluginData.current
    showPending.value = Boolean(pluginData.pending_application)
  } catch (error: any) {
    errorText.value = error?.data?.message || '插件不存在或尚未通过审核'
  } finally {
    loading.value = false
  }
}

async function selectVersion(versionId: string) {
  if (!versionId || !detail.value) return
  selectedVersion.value = await api<PluginVersion>(`/plugins/${articleId}/versions/${versionId}`)
  showPending.value = false
}

function openInstall(nextAction: 'copy' | 'download') {
  if (showPending.value) {
    toast.value = '待审核代码仅供上传者预览，审核通过后才能复制或下载。'
    return
  }
  if (nextAction === 'copy' && copyDisabled.value) {
    showToast('完整代码超过 100 KiB，请下载文件')
    return
  }
  action.value = nextAction
  confirmOpen.value = true
}

function showToast(message: string) {
  toast.value = message
  setTimeout(() => { toast.value = '' }, 1800)
}

async function submitReport() {
  if (!auth.isLoggedIn) {
    await navigateTo(`/login?redirect=${encodeURIComponent(route.fullPath)}`)
    return
  }
  try {
    await api(`/plugins/${articleId}/reports`, {
      method: 'POST',
      body: { report_type: reportType.value, description: reportDescription.value },
    })
    reportOpen.value = false
    reportDescription.value = ''
    showToast('举报已提交')
  } catch (error: any) {
    alert(error?.data?.message || '举报提交失败')
  }
}

onMounted(async () => {
  if (!auth.initialized) await auth.tryRefresh()
  await load()
})

useHead(() => ({ title: `${displayName.value} - 插件广场` }))
</script>

<template>
  <LoadingPanel v-if="loading" title="loading……" text="" />
  <div v-else-if="errorText" class="error-box">{{ errorText }}</div>
  <div v-else-if="detail && article" class="plugin-detail">
    <header class="plugin-header">
      <div class="header-main">
        <div class="title-line">
          <h1>{{ displayName }}</h1>
          <span v-if="detail.is_official" class="trust official">官方插件</span>
          <span v-if="detail.is_recommended" class="trust recommended">推荐插件</span>
        </div>
        <div class="tag-row">
          <span v-for="tag in displayTags" :key="tag.id" class="tag">{{ tag.name }}</span>
        </div>
      </div>
      <PluginRequestLevelBadge v-if="displayVersion" :level="displayVersion.final_request_level" />
    </header>

    <div v-if="detail.pending_application" class="pending-banner">
      <div>
        <strong>当前显示的是待审核版本 v{{ detail.pending_application.snapshot.version }}</strong>
        <p>此版本仅你和管理员可见，公开页面仍展示上一个已审核版本。</p>
      </div>
      <button
        v-if="detail.current"
        type="button"
        class="archive-action-button"
        @click="showPending = !showPending; selectedVersion = detail.current"
      >{{ showPending ? '切到已审核代码' : '查看待审核代码' }}</button>
    </div>

    <div v-if="!detail.is_listed" class="down-banner">
      <strong>插件已下架</strong>
      <span>{{ detail.down_reason || '该插件暂不在广场公开展示。' }}</span>
    </div>

    <nav class="tabs" aria-label="插件内容">
      <div class="tab-options">
        <button type="button" :class="{ active: activeTab === 'article' }" @click="activeTab = 'article'">原文</button>
        <button type="button" :class="{ active: activeTab === 'code' }" @click="activeTab = 'code'">代码</button>
        <button type="button" :class="{ active: activeTab === 'analysis' }" @click="activeTab = 'analysis'">请求分析</button>
      </div>
      <div class="article-links">
        <NuxtLink v-if="article.version_count > 1" :to="`/article/${articleId}/history`">历史版本</NuxtLink>
        <a :href="`https://www.luogu.com.cn/article/${articleId}`" target="_blank" rel="noopener noreferrer">洛谷原文</a>
      </div>
    </nav>

    <section v-if="activeTab === 'article'" class="tab-content article-tab">
      <article ref="articleRef" class="lg-content" v-html="articleHtml" />
    </section>

    <section v-else-if="activeTab === 'code' && displayVersion" class="tab-content code-tab">
      <div class="code-toolbar">
        <div class="version-picker">
          <label for="plugin-version">代码版本</label>
          <select
            id="plugin-version"
            :value="showPending ? 'pending' : String(displayVersion.id)"
            @change="selectVersion(($event.target as HTMLSelectElement).value)"
          >
            <option v-if="showPending" value="pending">v{{ displayVersion.version }} · 待审核</option>
            <option v-for="version in detail.versions" :key="version.id" :value="String(version.id)">
              v{{ version.version }}{{ version.is_current ? ' · 当前正式版' : '' }}
            </option>
          </select>
          <span v-if="displayVersion.published_at">发布于 {{ format(displayVersion.published_at) }}</span>
        </div>
        <div class="code-actions">
          <button
            type="button"
            class="archive-action-button"
            :disabled="copyDisabled"
            :title="copyDisabled ? '完整代码超过 100 KiB，仅支持下载' : '复制代码'"
            @click="openInstall('copy')"
          >复制代码</button>
          <button type="button" class="archive-action-button" title="下载代码" @click="openInstall('download')">下载文件</button>
        </div>
      </div>
      <div v-if="codePreview.truncated" class="code-truncation" role="status">
        <strong>代码较长，已截断显示</strong>
        <span>页面最多展示前 1000 行且不超过 50 KiB，完整代码未被修改。</span>
      </div>
      <div v-if="copyDisabled" class="copy-restriction" role="status">
        <strong>复制已禁用</strong>
        <span>完整代码超过 100 KiB，请下载文件。</span>
      </div>
      <pre class="code-view"><code>{{ codePreview.code }}</code></pre>
      <dl class="compat-grid">
        <div><dt>运行方式</dt><dd>{{ runtimeMode(displayVersion.runtime_mode) }}</dd></div>
        <div><dt>兼容设备</dt><dd>{{ [displayVersion.supports_desktop ? '桌面端' : '', displayVersion.supports_mobile ? '移动端' : ''].filter(Boolean).join('、') }}</dd></div>
        <div><dt>最后验证</dt><dd>{{ displayVersion.last_verified_on }}</dd></div>
        <div><dt>SHA-256</dt><dd><code>{{ displayVersion.code_sha256 }}</code></dd></div>
      </dl>
    </section>

    <section v-else-if="activeTab === 'analysis' && displayVersion" class="tab-content analysis-tab">
      <div class="level-comparison" :class="{ single: displayVersion.admin_request_level === null }">
        <div><span>用户提交等级</span><PluginRequestLevelBadge :level="displayVersion.user_request_level" /></div>
        <div v-if="displayVersion.admin_request_level !== null">
          <span>管理员更改等级</span>
          <PluginRequestLevelBadge :level="displayVersion.admin_request_level" />
        </div>
      </div>
      <section>
        <h2>上传者请求分析</h2>
        <div class="lg-content analysis-content" v-html="userAnalysisHtml" />
      </section>
      <section v-if="displayVersion.admin_request_analysis">
        <h2>管理组请求分析</h2>
        <div class="lg-content analysis-content" v-html="adminAnalysisHtml" />
      </section>
    </section>

    <footer class="detail-footer">
      <span>文章编号 {{ articleId }}</span>
      <div>
        <NuxtLink v-if="detail.is_owner" :to="`/plugin/submit?article_id=${articleId}`" class="archive-action-button">提交更新</NuxtLink>
        <button type="button" class="archive-action-button" @click="reportOpen = !reportOpen">举报插件</button>
      </div>
    </footer>

    <form v-if="reportOpen" class="report-form" @submit.prevent="submitReport">
      <h2>举报插件</h2>
      <select v-model="reportType">
        <option value="dangerous_request">危险请求</option>
        <option value="malicious_code">恶意代码</option>
        <option value="broken">失效</option>
        <option value="copyright">侵权</option>
        <option value="misleading">信息不实</option>
        <option value="other">其他</option>
      </select>
      <textarea v-model.trim="reportDescription" minlength="10" maxlength="5000" rows="5" placeholder="请至少填写 10 个字的具体说明" required />
      <button type="submit" class="archive-action-button">提交举报</button>
    </form>

    <p v-if="toast" class="toast">{{ toast }}</p>
    <PluginInstallConfirm
      v-if="displayVersion"
      :open="confirmOpen"
      :article-id="articleId"
      :plugin-name="displayName"
      :version="displayVersion"
      :action="action"
      :public-download="detail.is_listed"
      @close="confirmOpen = false"
      @done="showToast"
      @analysis="activeTab = 'analysis'; confirmOpen = false"
    />
  </div>
</template>

<style scoped>
.plugin-detail { display: grid; gap: 18px; }
.plugin-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; min-height: 130px; box-sizing: border-box; padding: 24px 28px; border: 1px solid var(--hero-border); border-radius: 8px; background: var(--hero-bg); }
.header-main { min-width: 0; }
.title-line { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; }
.title-line h1 { margin: 0; font-size: 29px; overflow-wrap: anywhere; }
.trust, .tag { border-radius: 4px; padding: 2px 8px; font-size: 12px; }
.official { background: var(--lg-blue); color: #fff; }
.recommended { background: var(--lg-yellow); color: #332800; }
.tag-row { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 13px; }
.tag { border: 1px solid var(--border); color: var(--text-muted); }
.pending-banner, .down-banner { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 13px 16px; border-left: 4px solid var(--lg-orange); background: var(--surface); }
.pending-banner p { margin: 3px 0 0; color: var(--text-muted); font-size: 13px; }
.down-banner { justify-content: flex-start; border-left-color: var(--lg-red); }
.tabs { display: flex; align-items: flex-end; justify-content: space-between; gap: 22px; border-bottom: 1px solid var(--border); }
.tab-options { display: flex; gap: 22px; }
.tabs button { border: 0; border-bottom: 3px solid transparent; background: transparent; color: var(--text-muted); padding: 10px 3px; font: inherit; font-size: 16px; cursor: pointer; }
.tabs button.active { border-bottom-color: var(--link); color: var(--link); font-weight: 600; }
.article-links { display: flex; align-items: center; gap: 14px; padding: 10px 3px 12px; white-space: nowrap; font-size: 14px; }
.tab-content { min-width: 0; padding: 22px 24px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.code-toolbar { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.version-picker { display: grid; grid-template-columns: auto minmax(150px, 250px); align-items: center; gap: 6px 10px; }
.version-picker > span { grid-column: 2; color: var(--text-muted); font-size: 12px; }
select, textarea { border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); padding: 8px 10px; font: inherit; }
.code-actions { display: flex; gap: 9px; }
.code-truncation { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 10px; margin-bottom: 10px; padding: 10px 12px; border-left: 4px solid var(--lg-yellow); background: color-mix(in srgb, var(--lg-yellow) 10%, var(--surface)); }
.code-truncation strong { font-size: 14px; }
.code-truncation span { color: var(--text-muted); font-size: 13px; }
.copy-restriction { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 10px; margin-bottom: 10px; padding: 10px 12px; border-left: 4px solid var(--lg-red); background: color-mix(in srgb, var(--lg-red) 8%, var(--surface)); }
.copy-restriction strong { font-size: 14px; }
.copy-restriction span { color: var(--text-muted); font-size: 13px; }
.compat-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 18px 0 0; border-top: 1px solid var(--border); border-left: 1px solid var(--border); }
.compat-grid > div { min-width: 0; padding: 11px 12px; border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); }
.compat-grid .wide { grid-column: 1 / -1; }
.compat-grid dt { color: var(--text-muted); font-size: 12px; }
.compat-grid dd { margin: 3px 0 0; overflow-wrap: anywhere; }
.compat-grid code { font-size: 11px; }
.code-view { max-height: 620px; overflow: auto; margin: 0; padding: 16px; border-radius: 6px; background: var(--hover); font-size: 13px; line-height: 1.55; white-space: pre; }
.level-comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin-bottom: 28px; background: var(--border); border: 1px solid var(--border); }
.level-comparison.single { grid-template-columns: minmax(0, 1fr); }
.level-comparison > div { display: grid; align-content: center; justify-items: start; gap: 8px; min-height: 82px; padding: 13px; background: var(--surface); }
.level-comparison span { color: var(--text-muted); font-size: 13px; }
.analysis-tab > section + section { margin-top: 28px; padding-top: 24px; border-top: 1px solid var(--border); }
.analysis-tab h2 { margin: 0 0 13px; font-size: 19px; }
.analysis-content { min-height: 40px; }
.detail-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; color: var(--text-muted); font-size: 13px; }
.detail-footer > div { display: flex; align-items: center; gap: 12px; }
.report-form { display: grid; grid-template-columns: 180px minmax(0, 1fr) auto; align-items: start; gap: 10px; padding: 16px; border: 1px solid var(--border); background: var(--surface); }
.report-form h2 { grid-column: 1 / -1; margin: 0 0 4px; font-size: 18px; }
.report-form textarea { resize: vertical; }
.toast { position: fixed; z-index: 900; left: 50%; bottom: 28px; transform: translateX(-50%); margin: 0; padding: 9px 15px; border-radius: 6px; background: #222; color: #fff; box-shadow: 0 8px 24px rgba(0,0,0,.24); }
.error-box { padding: 36px; border: 1px solid var(--border); color: var(--lg-red); text-align: center; }
@media (max-width: 760px) {
  .plugin-header, .pending-banner, .code-toolbar, .detail-footer { align-items: flex-start; flex-direction: column; }
  .tabs { align-items: stretch; flex-direction: column; gap: 0; }
  .tab-options { overflow-x: auto; }
  .article-links { align-self: flex-end; padding-top: 7px; }
  .compat-grid, .level-comparison { grid-template-columns: 1fr; }
  .compat-grid .wide { grid-column: auto; }
  .report-form { grid-template-columns: 1fr; }
  .report-form h2 { grid-column: auto; }
  .tab-content { padding: 17px 15px; }
}
</style>
