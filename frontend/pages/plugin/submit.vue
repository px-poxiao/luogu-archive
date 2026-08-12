<script setup lang="ts">
import type { PluginDetail, PluginSnapshot, PluginTag } from '~/types/plugin'
import { emptyPluginSnapshot } from '~/types/plugin'

const route = useRoute()
const auth = useAuthStore()
const api = useApi()

const articleId = ref(String(route.query.article_id || '').trim())
const confirmedArticleId = ref('')
const tags = ref<PluginTag[]>([])
const snapshot = ref<PluginSnapshot>(emptyPluginSnapshot())
const article = ref<any>(null)
const editing = ref(false)
const hasPending = ref(false)
const blocked = ref(false)
const loading = ref(true)
const submitting = ref(false)
const submitSucceeded = ref(false)
const message = ref('')
const errorText = ref('')

function snapshotFromVersion(detail: PluginDetail, fullCode: string): PluginSnapshot {
  const version = detail.current!
  return {
    summary: detail.summary || '',
    version: '',
    code: fullCode,
    download_filename: version.download_filename,
    user_request_level: version.user_request_level,
    user_request_analysis: version.user_request_analysis,
    tag_ids: detail.tags.map(tag => tag.id),
    runtime_mode: version.runtime_mode,
    supports_desktop: version.supports_desktop,
    supports_mobile: version.supports_mobile,
    last_verified_on: new Date().toISOString().slice(0, 10),
    admin_request_level: null,
    admin_request_analysis: null,
  }
}

async function loadFullCode(path: string): Promise<string> {
  const blob = await api<Blob>(path, { responseType: 'blob' })
  return blob.text()
}

async function inspectArticle() {
  if (!articleId.value) return
  errorText.value = ''
  article.value = null
  if (confirmedArticleId.value !== articleId.value) {
    editing.value = false
    hasPending.value = false
    blocked.value = false
    message.value = ''
    snapshot.value = emptyPluginSnapshot()
  }
  try {
    article.value = await api(`/article/${articleId.value}`)
    confirmedArticleId.value = articleId.value
    try {
      const detail = await api<PluginDetail>(`/plugins/${articleId.value}`)
      if (!detail.is_owner) {
        blocked.value = true
        errorText.value = '该文章已有插件，只有当前上传者可以提交更新。'
        return
      }
      editing.value = !detail.pending_only
      if (detail.pending_application) {
        hasPending.value = true
        const fullCode = await loadFullCode(`/plugins/applications/${detail.pending_application.id}/download`)
        snapshot.value = { ...detail.pending_application.snapshot, code: fullCode }
        message.value = '已载入你的待审核申请，可以查看但不能重复提交。'
      } else if (detail.current) {
        const fullCode = await loadFullCode(`/plugins/${articleId.value}/download/${detail.current.id}`)
        snapshot.value = snapshotFromVersion(detail, fullCode)
      }
    } catch (error: any) {
      if (error?.statusCode !== 404 && error?.response?.status !== 404) throw error
      editing.value = false
    }
  } catch (error: any) {
    errorText.value = error?.data?.message || '文章不存在或尚未完整收录'
  }
}

async function submit() {
  errorText.value = ''
  message.value = ''
  submitSucceeded.value = false
  if (!auth.isLoggedIn) {
    await navigateTo(`/login?redirect=${encodeURIComponent(route.fullPath)}`)
    return
  }
  if (!article.value) {
    errorText.value = '请先确认文章编号'
    return
  }
  if (confirmedArticleId.value !== articleId.value) {
    errorText.value = '文章编号已改变，请重新确认文章'
    return
  }
  if (hasPending.value) {
    errorText.value = '已有待审核申请，请先等待审核或在“我的插件”中撤销。'
    return
  }
  if (!snapshot.value.supports_desktop && !snapshot.value.supports_mobile) {
    errorText.value = '至少选择一种兼容设备'
    return
  }
  submitting.value = true
  try {
    if (editing.value) {
      await api(`/plugins/${articleId.value}/applications/update`, {
        method: 'POST',
        body: snapshot.value,
      })
    } else {
      await api('/plugins/applications/publish', {
        method: 'POST',
        body: { article_id: articleId.value, snapshot: snapshot.value },
      })
    }
    hasPending.value = true
    submitSucceeded.value = true
    message.value = '提交成功。申请已进入审核，结果会发送到你的注册邮箱。'
  } catch (error: any) {
    errorText.value = error?.data?.message || '提交失败'
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  if (!auth.initialized) await auth.tryRefresh()
  if (!auth.isLoggedIn) {
    await navigateTo(`/login?redirect=${encodeURIComponent(route.fullPath)}`)
    return
  }
  try { tags.value = await api<PluginTag[]>('/plugins/tags') } catch {}
  if (articleId.value) await inspectArticle()
  loading.value = false
})

useHead({ title: '提交插件 - 洛谷档案馆' })
</script>

<template>
  <LoadingPanel v-if="loading" title="loading……" text="" />
  <div v-else class="submit-page">
    <header class="page-head">
      <div>
        <h1>{{ editing ? '提交版本更新' : '发布插件' }}</h1>
        <p>插件原文始终使用文章的最新归档版本，代码作为独立内容提交审核。</p>
      </div>
      <NuxtLink to="/plugin/manage">返回我的插件</NuxtLink>
    </header>

    <section class="article-picker">
      <label>
        <span>洛谷文章编号</span>
        <div class="input-action">
          <input v-model.trim="articleId" maxlength="16" placeholder="例如 jbekb3o8" :disabled="editing || hasPending">
          <button type="button" @click="inspectArticle">确认文章</button>
        </div>
      </label>
      <div v-if="article" class="article-result">
        <strong>{{ article.title }}</strong>
        <span>文章 {{ article.article_id }} 已收录</span>
      </div>
    </section>

    <p v-if="message" class="message ok" :class="{ submitted: submitSucceeded }" role="status">{{ message }}</p>
    <p v-if="errorText" class="message error">{{ errorText }}</p>

    <form v-if="article && !blocked" class="plugin-form" @submit.prevent="submit">
      <PluginSnapshotForm v-model="snapshot" :tags="tags" />
      <div class="submit-actions">
        <span>提交即表示你确认代码和请求说明真实、完整。</span>
        <button type="submit" :disabled="submitting || hasPending">{{ hasPending ? '已有待审核申请' : submitting ? '提交中…' : '提交审核' }}</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.submit-page { display: grid; gap: 22px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; padding: 22px 26px; border: 1px solid var(--hero-border); border-radius: 8px; background: var(--hero-bg); }
.page-head h1 { margin: 0; font-size: 27px; }
.page-head p { margin: 7px 0 0; color: var(--text-muted); }
.article-picker, .plugin-form { padding: 22px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.article-picker { display: grid; gap: 14px; }
.article-picker label { display: grid; gap: 7px; font-weight: 600; }
.input-action { display: flex; gap: 9px; }
.input-action input { flex: 1; min-width: 0; }
input, button { box-sizing: border-box; border: 1px solid var(--border); border-radius: 6px; padding: 9px 11px; background: var(--surface); color: var(--text); font: inherit; }
button { cursor: pointer; }
.input-action button, .submit-actions button { border-color: var(--link); background: var(--link); color: #fff; }
.article-result { display: flex; justify-content: space-between; gap: 12px; color: var(--text-muted); }
.article-result strong { color: var(--text); }
.message { margin: 0; padding: 10px 13px; border-left: 3px solid; background: var(--surface); }
.message.ok { border-color: var(--lg-green); }
.message.submitted { position: fixed; z-index: 850; left: 50%; bottom: 28px; width: min(560px, calc(100vw - 32px)); box-sizing: border-box; transform: translateX(-50%); border: 1px solid var(--lg-green); border-left-width: 5px; border-radius: 7px; background: var(--surface); color: var(--text); font-size: 15px; font-weight: 600; box-shadow: 0 12px 36px rgba(0, 0, 0, .22); }
.message.error { border-color: var(--lg-red); color: var(--lg-red); }
.submit-actions { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 28px; padding-top: 20px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 13px; }
.submit-actions button { padding-inline: 20px; font-size: 15px; }
.submit-actions button:disabled { opacity: .55; cursor: default; }
@media (max-width: 650px) {
  .page-head, .article-result, .submit-actions { align-items: flex-start; flex-direction: column; }
  .input-action { flex-direction: column; }
}
</style>
