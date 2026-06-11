<script setup lang="ts">
definePageMeta({ layout: 'default' })

type FixMode = 'local' | 'ai'
type DiffKind = 'same' | 'add' | 'remove' | 'change'

interface ArticleDetail {
  article_id: string
  title: string
  content_md: string
}

interface LocalFixResp {
  mode: 'local'
  content: string
  changed: boolean
  notes: string[]
}

interface DiffRow {
  kind: DiffKind
  left: string
  right: string
  leftNo: number | null
  rightNo: number | null
}

const api = useApi()
const auth = useAuthStore()
const config = useRuntimeConfig()

const fixMode = ref<FixMode>('local')
const sourceText = ref('')
const articleLink = ref('')
const articleTitle = ref('')
const originalText = ref('')
const fixedText = ref('')
const thoughts = ref('')
const notes = ref<string[]>([])
const logs = ref<string[]>([])
const busy = ref(false)
const copied = ref(false)
const errorMessage = ref('')

const canRun = computed(() => {
  if (busy.value) return false
  return sourceText.value.trim().length > 0 || articleLink.value.trim().length > 0
})

const diffRows = computed(() => buildDiff(originalText.value, fixedText.value))
const changedCount = computed(() =>
  diffRows.value.filter((row) => row.kind === 'add' || row.kind === 'remove' || row.kind === 'change').length,
)

function addLog(message: string) {
  logs.value.push(message)
}

function parseArticleId(input: string): string {
  let value = input.trim()
  if (/^[A-Za-z0-9_-]{1,64}$/.test(value)) return value
  if (/^(?:www\.)?luogu\./i.test(value)) value = `https://${value}`
  if (/^https?:\/\//i.test(value)) {
    const url = new URL(value)
    const hosts = ['www.luogu.com.cn', 'luogu.com.cn', 'www.luogu.com', 'luogu.com']
    if (!hosts.includes(url.hostname.toLowerCase())) throw new Error('只支持洛谷文章链接')
    value = url.pathname
  }
  const m = value.match(/^\/(?:article|atricle)\/([A-Za-z0-9_-]{1,64})\/?$/i)
  if (!m) throw new Error('支持 /article/{id}、洛谷文章链接或纯文章 ID')
  return m[1]
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitArticleReady(id: string): Promise<ArticleDetail> {
  for (let i = 0; i < 24; i++) {
    if (i > 0) await sleep(1500)
    try {
      return await api<ArticleDetail>(`/article/${id}`)
    } catch (err: any) {
      const status = err?.statusCode || err?.response?.status
      if (status && status !== 404) throw err
      if (i === 0) addLog('等待文章收录完成')
    }
  }
  throw new Error('文章暂未收录完成，请稍后再试')
}

async function loadInputText(): Promise<string> {
  const link = articleLink.value.trim()
  const pasted = sourceText.value.trim()
  if (!link) {
    articleTitle.value = ''
    return sourceText.value
  }

  if (pasted) {
    addLog('检测到同时提供 Markdown 和文章链接，已优先使用文章链接')
  }
  const id = parseArticleId(link)
  addLog(`提交文章 ${id} 到保存队列`)
  const saved = await api<{ task_id: string; merged: boolean }>('/save', {
    method: 'POST',
    body: { content_type: 'article', id },
  })
  addLog(saved.merged ? '复用已有保存任务' : '已派发保存任务')
  addLog('读取文章正文')
  const article = await waitArticleReady(id)
  articleTitle.value = article.title
  return article.content_md
}

async function runFix() {
  if (!canRun.value) return
  busy.value = true
  errorMessage.value = ''
  notes.value = []
  logs.value = []
  thoughts.value = ''
  fixedText.value = ''
  copied.value = false

  try {
    const input = await loadInputText()
    originalText.value = input
    if (fixMode.value === 'local') {
      addLog('执行本地格式修正')
      const resp = await api<LocalFixResp>('/solution-fix/local', {
        method: 'POST',
        body: { content: input },
      })
      fixedText.value = resp.content
      notes.value = resp.notes
      addLog(resp.changed ? '本地修正完成' : '未发现需要修正的格式问题')
    } else {
      if (!auth.isLoggedIn) throw new Error('AI 修正需要先登录')
      addLog('连接 AI 修正流')
      await runAiFix(input)
    }
  } catch (err: any) {
    errorMessage.value = err?.data?.message || err?.message || '修正失败'
  } finally {
    busy.value = false
  }
}

async function runAiFix(input: string) {
  const base = import.meta.server
    ? config.apiInternalUrl
    : config.public.apiBaseUrl
  const resp = await fetch(`${base}/api/v1/solution-fix/ai`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(auth.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {}),
    },
    body: JSON.stringify({ content: input }),
  })
  if (!resp.ok || !resp.body) {
    let message = `AI 修正失败（${resp.status}）`
    try {
      const data = await resp.json()
      message = data?.message || message
    } catch {
      /* ignore */
    }
    throw new Error(message)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (!line.trim()) continue
      const msg = JSON.parse(line)
      if (msg.event === 'meta') {
        addLog(`模型：${msg.data.model}`)
      } else if (msg.event === 'thought') {
        thoughts.value += msg.data
      } else if (msg.event === 'content') {
        fixedText.value += msg.data
      } else if (msg.event === 'done') {
        addLog('AI 修正完成')
      } else if (msg.event === 'error') {
        throw new Error(msg.data)
      }
    }
  }
}

async function copyResult() {
  if (!fixedText.value) return
  await navigator.clipboard.writeText(fixedText.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1400)
}

function buildDiff(leftText: string, rightText: string): DiffRow[] {
  if (!leftText && !rightText) return []
  const a = leftText.replace(/\r\n/g, '\n').split('\n')
  const b = rightText.replace(/\r\n/g, '\n').split('\n')
  const n = a.length
  const m = b.length
  const dp = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const ops: Array<{ kind: 'same' | 'add' | 'remove'; text: string; line: number }> = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ kind: 'same', text: a[i], line: i + 1 })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ kind: 'remove', text: a[i], line: i + 1 })
      i++
    } else {
      ops.push({ kind: 'add', text: b[j], line: j + 1 })
      j++
    }
  }
  while (i < n) ops.push({ kind: 'remove', text: a[i], line: ++i })
  while (j < m) ops.push({ kind: 'add', text: b[j], line: ++j })

  const rows: DiffRow[] = []
  for (let k = 0; k < ops.length; k++) {
    const op = ops[k]
    const next = ops[k + 1]
    if (op.kind === 'remove' && next?.kind === 'add') {
      rows.push({ kind: 'change', left: op.text, right: next.text, leftNo: op.line, rightNo: next.line })
      k++
    } else if (op.kind === 'same') {
      rows.push({ kind: 'same', left: op.text, right: op.text, leftNo: op.line, rightNo: op.line })
    } else if (op.kind === 'remove') {
      rows.push({ kind: 'remove', left: op.text, right: '', leftNo: op.line, rightNo: null })
    } else {
      rows.push({ kind: 'add', left: '', right: op.text, leftNo: null, rightNo: op.line })
    }
  }
  return rows
}
</script>

<template>
  <div class="fix-page">
    <PageHero
      title="题解修"
      subtitle="对题解 Markdown 做格式修正，保留洛谷扩展语法；AI 模式需要登录。"
    />

    <section class="fix-shell">
      <div class="input-panel">
        <div class="panel-head">
          <h2>输入</h2>
        </div>

        <textarea
          v-model="sourceText"
          class="source-input textarea"
          placeholder="粘贴题解 Markdown..."
          spellcheck="false"
        />

        <label class="article-link-field">
          <span>粘贴文章链接...</span>
          <input
            v-model="articleLink"
            class="source-input"
            placeholder="/article/xxxxxxxx、www.luogu.com.cn/article/xxxxxxxx 或纯 ID"
            spellcheck="false"
          >
        </label>

        <div class="mode-row" aria-label="修正模式">
          <button type="button" :class="{ active: fixMode === 'local' }" @click="fixMode = 'local'">
            本地修正
          </button>
          <button type="button" :class="{ active: fixMode === 'ai' }" @click="fixMode = 'ai'">
            AI 修正
          </button>
        </div>

        <button class="primary-btn" type="button" :disabled="!canRun" @click="runFix">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
          </svg>
          <span>{{ busy ? '处理中...' : '开始修正' }}</span>
        </button>

        <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
        <div v-if="notes.length" class="note-list">
          <span v-for="note in notes" :key="note">{{ note }}</span>
        </div>
      </div>

      <div class="result-panel">
        <div class="result-toolbar">
          <div>
            <h2>{{ articleTitle || '修正结果' }}</h2>
            <p>{{ fixedText ? `变更行 ${changedCount}` : '等待输入后生成差异对比' }}</p>
          </div>
          <button type="button" class="copy-btn" :disabled="!fixedText" @click="copyResult">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M8 8h10v12H8zM6 16H4V4h12v2" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" />
            </svg>
            <span>{{ copied ? '已复制' : '复制' }}</span>
          </button>
        </div>

        <div class="diff-head">
          <span>原文</span>
          <span>修正后</span>
        </div>
        <div class="diff-view">
          <div
            v-for="(row, idx) in diffRows"
            :key="idx"
            class="diff-row"
            :class="row.kind"
          >
            <div class="line-cell">
              <span class="line-no">{{ row.leftNo || '' }}</span>
              <code>{{ row.left }}</code>
            </div>
            <div class="line-cell">
              <span class="line-no">{{ row.rightNo || '' }}</span>
              <code>{{ row.right }}</code>
            </div>
          </div>
          <div v-if="!diffRows.length" class="empty-state">暂无结果</div>
        </div>
      </div>
    </section>

    <section class="trace-panel">
      <details open>
        <summary>模型思路 / 处理记录</summary>
        <div class="trace-grid">
          <pre>{{ thoughts || '当前模型未返回可展示的思考内容。' }}</pre>
          <ul>
            <li v-for="(log, idx) in logs" :key="idx">{{ log }}</li>
            <li v-if="!logs.length">等待开始</li>
          </ul>
        </div>
      </details>
    </section>
  </div>
</template>

<style scoped>
.fix-page {
  display: grid;
  gap: 18px;
}

.fix-shell {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 18px;
  align-items: stretch;
}

.input-panel,
.result-panel,
.trace-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.input-panel {
  padding: 18px;
  display: grid;
  grid-template-rows: auto minmax(220px, 1fr) auto auto auto auto;
  gap: 14px;
  min-height: 560px;
}

.panel-head,
.result-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.3;
}

.result-toolbar p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.segmented,
.mode-row {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  background: var(--surface);
}

.segmented button,
.mode-row button {
  border: 0;
  border-right: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  min-height: 34px;
  padding: 0 12px;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
}

.segmented button:last-child,
.mode-row button:last-child {
  border-right: 0;
}

.segmented button.active,
.mode-row button.active {
  background: color-mix(in srgb, var(--link) 10%, transparent);
  color: var(--link);
}

.article-link-field {
  display: grid;
  gap: 6px;
}

.article-link-field span {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 650;
}

.mode-row {
  width: 100%;
}

.mode-row button {
  flex: 1;
}

.source-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  padding: 10px 12px;
}

.textarea {
  min-height: 260px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.55;
}

.source-input:focus {
  outline: 2px solid color-mix(in srgb, var(--link) 28%, transparent);
  border-color: var(--link);
}

.primary-btn,
.copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--link);
  border-radius: 6px;
  background: var(--link);
  color: #fff;
  min-height: 40px;
  padding: 0 16px;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
}

.primary-btn svg,
.copy-btn svg {
  width: 17px;
  height: 17px;
}

.primary-btn:disabled,
.copy-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.copy-btn {
  background: var(--surface);
  color: var(--text);
  border-color: var(--border);
  font-weight: 500;
}

.copy-btn:hover:not(:disabled) {
  color: var(--link);
  border-color: var(--link);
}

.error-text {
  margin: 0;
  color: var(--lg-red);
  font-size: 13px;
}

.note-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.note-list span {
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  padding: 2px 9px;
  font-size: 12px;
}

.result-panel {
  min-width: 0;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  overflow: hidden;
}

.result-toolbar {
  padding: 16px 18px;
  border-bottom: 1px solid var(--border);
}

.diff-head {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-bottom: 1px solid var(--border);
  background: var(--hover);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
}

.diff-head span {
  padding: 7px 12px;
}

.diff-head span + span {
  border-left: 1px solid var(--border);
}

.diff-view {
  overflow: auto;
  min-height: 460px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
}

.diff-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  min-height: 24px;
}

.line-cell {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  border-bottom: 1px solid color-mix(in srgb, var(--border) 45%, transparent);
  min-width: 0;
}

.line-cell + .line-cell {
  border-left: 1px solid var(--border);
}

.line-no {
  padding: 3px 8px;
  color: var(--text-muted);
  text-align: right;
  user-select: none;
  background: color-mix(in srgb, var(--hover) 70%, transparent);
}

.line-cell code {
  padding: 3px 10px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--text);
  font: inherit;
}

.diff-row.add .line-cell:nth-child(2),
.diff-row.change .line-cell:nth-child(2) {
  background: color-mix(in srgb, var(--lg-green) 14%, transparent);
}

.diff-row.remove .line-cell:nth-child(1),
.diff-row.change .line-cell:nth-child(1) {
  background: color-mix(in srgb, var(--lg-red) 12%, transparent);
}

.empty-state {
  min-height: 360px;
  display: grid;
  place-items: center;
  color: var(--text-muted);
}

.trace-panel {
  overflow: hidden;
}

.trace-panel summary {
  cursor: pointer;
  padding: 12px 16px;
  font-weight: 700;
  border-bottom: 1px solid var(--border);
}

.trace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 0;
}

.trace-grid pre,
.trace-grid ul {
  margin: 0;
  min-height: 120px;
  max-height: 260px;
  overflow: auto;
  padding: 14px 16px;
  box-sizing: border-box;
}

.trace-grid pre {
  white-space: pre-wrap;
  color: var(--text-muted);
  border-right: 1px solid var(--border);
  font: 13px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.trace-grid ul {
  color: var(--text-muted);
  font-size: 13px;
  padding-left: 34px;
}

@media (max-width: 980px) {
  .fix-shell,
  .trace-grid {
    grid-template-columns: 1fr;
  }

  .input-panel {
    min-height: auto;
  }

  .trace-grid pre {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }
}

@media (max-width: 640px) {
  .panel-head,
  .result-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .copy-btn,
  .primary-btn {
    width: 100%;
  }

  .diff-head,
  .diff-row {
    grid-template-columns: 1fr;
  }

  .diff-head span + span,
  .line-cell + .line-cell {
    border-left: 0;
  }
}
</style>
