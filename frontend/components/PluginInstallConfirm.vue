<script setup lang="ts">
import type { PluginVersion } from '~/types/plugin'
import { PLUGIN_CODE_COPY_MAX_BYTES, formatBytes, isBinaryCode } from '~/utils/pluginCode'

const props = defineProps<{
  open: boolean
  articleId: string
  pluginName: string
  version: PluginVersion
  action: 'copy' | 'download'
  publicDownload: boolean
}>()
const emit = defineEmits<{ close: []; done: [message: string]; analysis: [] }>()
const api = useApi()
const config = useRuntimeConfig()
const { runtimeMode } = usePluginLabels()
const binary = computed(() => isBinaryCode(props.version.code_encoding))
const codeBytes = computed(() => props.version.code_bytes)
const copyBlocked = computed(() => props.action === 'copy'
  && (binary.value || codeBytes.value > PLUGIN_CODE_COPY_MAX_BYTES))
const codeSize = computed(() => formatBytes(codeBytes.value))

async function confirm() {
  if (binary.value && props.action === 'copy') {
    emit('done', '二进制文件不能复制，请下载文件')
    emit('close')
    return
  }
  if (copyBlocked.value) {
    emit('done', '完整代码超过 100 KiB，请下载文件')
    emit('close')
    return
  }
  try {
    const path = `/plugins/${props.articleId}/download/${props.version.id}`

    // 公开下载由真实文件请求在后端记数，不再依赖可绕过的客户端累计接口。
    if (props.action === 'download' && props.publicDownload) {
      const base = String(config.public.apiBaseUrl || '').replace(/\/$/, '')
      const anchor = document.createElement('a')
      anchor.href = `${base}/api/v1${path}`
      anchor.download = props.version.download_filename
      anchor.hidden = true
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      emit('done', '下载已经开始')
      emit('close')
      return
    }

    // 复制只在剪贴板写入成功后上报，读取代码本身不应被算作下载。
    const codePath = props.action === 'copy' ? `${path}?track_usage=false` : path
    const blob = await api<Blob>(codePath, { responseType: 'blob' })
    if (props.action === 'copy') {
      await navigator.clipboard.writeText(await blob.text())
      try {
        await api(`/plugins/${props.articleId}/increment_copy/${props.version.id}`, { method: 'POST' })
      } catch (e) {
        // 统计失败不能影响已经完成的复制操作。
      }
      emit('done', '代码已复制')
    } else {
      // 非公开下载已经在读取文件时由后端完成记数。
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = props.version.download_filename
      anchor.click()
      URL.revokeObjectURL(url)
      emit('done', '下载已经开始')
    }
  } catch {
    emit('done', `${props.action === 'copy' ? '复制' : '下载'}失败，请重试`)
  }
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop" @click.self="emit('close')">
      <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="install-title">
        <header>
          <h2 id="install-title">确认{{ action === 'copy' ? '复制' : '下载' }}代码</h2>
          <button type="button" class="close" title="关闭" aria-label="关闭" @click="emit('close')">×</button>
        </header>
        <dl>
          <div><dt>插件</dt><dd>{{ pluginName }}</dd></div>
          <div><dt>版本</dt><dd>{{ version.version }}</dd></div>
          <div><dt>内容形式</dt><dd>{{ binary ? '二进制文件' : '文本代码' }}</dd></div>
          <div><dt>文件大小</dt><dd>{{ codeSize }}</dd></div>
          <div><dt>请求等级</dt><dd><PluginRequestLevelBadge :level="version.final_request_level" compact /></dd></div>
          <div><dt>运行方式</dt><dd>{{ runtimeMode(version.runtime_mode) }}</dd></div>
          <div><dt>最后验证</dt><dd>{{ version.last_verified_on }}</dd></div>
          <div><dt>SHA-256</dt><dd><code>{{ version.code_sha256 }}</code></dd></div>
        </dl>
        <p class="notice">代码由上传者提供，本站不会执行或自动验证代码。安装前请阅读请求分析并自行确认风险。</p>
        <p v-if="binary && action === 'copy'" class="copy-warning">
          这是二进制文件，不能复制，请下载文件。
        </p>
        <p v-else-if="copyBlocked" class="copy-warning">
          完整代码大小为 {{ codeSize }}，超过 100 KiB，不能复制，请下载文件。
        </p>
        <footer>
          <button type="button" class="analysis-link" @click="emit('analysis')">查看请求分析</button>
          <button type="button" class="archive-action-button" @click="emit('close')">取消</button>
          <button type="button" class="archive-action-button" :disabled="copyBlocked" @click="confirm">确认{{ action === 'copy' ? '复制' : '下载' }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 18px; background: rgba(0, 0, 0, .52); }
.dialog { width: min(620px, 100%); max-height: calc(100vh - 36px); overflow: auto; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); box-shadow: 0 18px 55px rgba(0, 0, 0, .28); }
header, footer { display: flex; align-items: center; padding: 16px 18px; }
header { justify-content: space-between; border-bottom: 1px solid var(--border); }
header h2 { margin: 0; font-size: 19px; }
.close { border: 0; background: transparent; color: var(--text-muted); font-size: 26px; cursor: pointer; }
dl { margin: 0; padding: 16px 18px; display: grid; gap: 11px; }
dl > div { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 12px; }
dt { color: var(--text-muted); }
dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
code { font-size: 12px; }
.notice { margin: 0 18px; padding: 11px 13px; border-left: 3px solid var(--lg-orange); background: var(--hover); color: var(--text-muted); font-size: 13px; }
.copy-warning { margin: 10px 18px 0; padding: 11px 13px; border-left: 3px solid var(--lg-yellow); background: color-mix(in srgb, var(--lg-yellow) 10%, var(--surface)); color: var(--text-muted); font-size: 13px; }
footer { justify-content: flex-end; gap: 10px; }
.analysis-link { margin-right: auto; border: 0; background: transparent; color: var(--link); }
@media (max-width: 520px) { dl > div { grid-template-columns: 1fr; gap: 3px; } }
</style>
