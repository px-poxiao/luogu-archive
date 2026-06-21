<script setup lang="ts">
interface VersionEntry {
  id: number
  title?: string | null
  content_md: string
  crawled_at: string
  is_current?: boolean
}

type DiffKind = 'same' | 'add' | 'remove' | 'change'

interface DiffRow {
  kind: DiffKind
  left: string
  right: string
  leftNo: number | null
  rightNo: number | null
}

const props = withDefaults(defineProps<{
  versions: VersionEntry[]
  emptyText?: string
}>(), {
  emptyText: '暂无历史版本',
})

const { render } = useMarkdown()
const { format } = useTime()

const openFull = ref<Set<number>>(new Set())
const copiedId = ref<number | null>(null)

const sortedVersions = computed(() =>
  [...props.versions].sort((a, b) =>
    new Date(b.crawled_at).getTime() - new Date(a.crawled_at).getTime(),
  ),
)

const groups = computed(() => {
  const buckets: Array<{ date: string; versions: VersionEntry[] }> = []
  const byDate = new Map<string, VersionEntry[]>()
  for (const version of sortedVersions.value) {
    const key = format(version.crawled_at, 'YYYY-MM-DD')
    const list = byDate.get(key) || []
    list.push(version)
    byDate.set(key, list)
  }
  for (const [date, versions] of byDate) {
    buckets.push({ date, versions })
  }
  return buckets
})

const diffCache = computed(() => {
  const cache = new Map<number, DiffRow[]>()
  for (const version of sortedVersions.value) {
    const prev = previousOf(version)
    cache.set(version.id, buildDiff(prev?.content_md || '', version.content_md || ''))
  }
  return cache
})

const statCache = computed(() => {
  const cache = new Map<number, { add: number; remove: number }>()
  for (const version of sortedVersions.value) {
    let add = 0
    let remove = 0
    for (const row of diffOf(version)) {
      if (row.kind === 'add') add++
      if (row.kind === 'remove') remove++
      if (row.kind === 'change') {
        add++
        remove++
      }
    }
    cache.set(version.id, { add, remove })
  }
  return cache
})

function previousOf(version: VersionEntry): VersionEntry | null {
  const idx = sortedVersions.value.findIndex((item) => item.id === version.id)
  if (idx < 0 || idx + 1 >= sortedVersions.value.length) return null
  return sortedVersions.value[idx + 1]
}

function diffOf(version: VersionEntry): DiffRow[] {
  return diffCache.value.get(version.id) || []
}

function diffStats(version: VersionEntry) {
  return statCache.value.get(version.id) || { add: 0, remove: 0 }
}

function toggleFull(id: number) {
  const next = new Set(openFull.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  openFull.value = next
}

async function copyVersion(version: VersionEntry) {
  await navigator.clipboard.writeText(version.content_md || '')
  copiedId.value = version.id
  setTimeout(() => {
    if (copiedId.value === version.id) copiedId.value = null
  }, 1400)
}

function htmlOf(version: VersionEntry) {
  return render(version.content_md || '')
}

function buildDiff(leftText: string, rightText: string): DiffRow[] {
  const a = leftText.replace(/\r\n/g, '\n').split('\n')
  const b = rightText.replace(/\r\n/g, '\n').split('\n')
  const n = a.length
  const m = b.length

  if (n * m > 2_000_000) {
    return buildSimpleDiff(a, b)
  }

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
  while (i < n) {
    ops.push({ kind: 'remove', text: a[i], line: i + 1 })
    i++
  }
  while (j < m) {
    ops.push({ kind: 'add', text: b[j], line: j + 1 })
    j++
  }

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

function buildSimpleDiff(a: string[], b: string[]): DiffRow[] {
  const rows: DiffRow[] = []
  const max = Math.max(a.length, b.length)
  for (let i = 0; i < max; i++) {
    const left = a[i]
    const right = b[i]
    if (left === right) {
      rows.push({ kind: 'same', left: left ?? '', right: right ?? '', leftNo: i + 1, rightNo: i + 1 })
    } else if (left === undefined) {
      rows.push({ kind: 'add', left: '', right: right ?? '', leftNo: null, rightNo: i + 1 })
    } else if (right === undefined) {
      rows.push({ kind: 'remove', left: left ?? '', right: '', leftNo: i + 1, rightNo: null })
    } else {
      rows.push({ kind: 'change', left, right, leftNo: i + 1, rightNo: i + 1 })
    }
  }
  return rows
}

function changedRows(rows: DiffRow[]): DiffRow[] {
  return rows.filter((row) => row.kind !== 'same')
}
</script>

<template>
  <div class="history-timeline">
    <p v-if="!sortedVersions.length" class="empty">{{ emptyText }}</p>

    <section v-for="group in groups" :key="group.date" class="day-group">
      <h2 class="day-title">{{ group.date }}</h2>

      <article v-for="version in group.versions" :key="version.id" class="version-card">
        <header class="version-head">
          <div class="version-meta">
            <strong>{{ version.title || `版本 ${version.id}` }}</strong>
            <span>{{ format(version.crawled_at, 'HH:mm:ss') }}</span>
            <span v-if="version.is_current" class="current-tag">当前版本</span>
          </div>
          <div class="version-actions">
            <span class="stat add">+{{ diffStats(version).add }}</span>
            <span class="stat remove">-{{ diffStats(version).remove }}</span>
            <button type="button" @click="toggleFull(version.id)">
              {{ openFull.has(version.id) ? '收起全文' : '查看全文' }}
            </button>
            <button type="button" @click="copyVersion(version)">
              {{ copiedId === version.id ? '已复制' : '复制原文' }}
            </button>
          </div>
        </header>

        <div class="diff-box">
          <div
            v-for="(row, idx) in changedRows(diffOf(version))"
            :key="idx"
            class="diff-row"
            :class="row.kind"
          >
            <span class="line-no">{{ row.leftNo || row.rightNo || '' }}</span>
            <code v-if="row.kind === 'remove'">- {{ row.left }}</code>
            <code v-else-if="row.kind === 'add'">+ {{ row.right }}</code>
            <code v-else>- {{ row.left }}<br>+ {{ row.right }}</code>
          </div>
          <div v-if="!changedRows(diffOf(version)).length" class="diff-empty">
            与上一版本相比没有正文变化
          </div>
        </div>

        <div v-if="openFull.has(version.id)" class="full-text">
          <article class="lg-content" v-html="htmlOf(version)" />
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.history-timeline {
  display: grid;
  gap: 22px;
}

.empty {
  padding: 34px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-muted);
  text-align: center;
}

.day-group {
  display: grid;
  gap: 12px;
}

.day-title {
  margin: 0;
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 700;
}

.version-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  overflow: hidden;
}

.version-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
}

.version-meta,
.version-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.version-meta {
  min-width: 0;
}

.version-meta strong {
  max-width: min(560px, 100%);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.version-meta span {
  color: var(--text-muted);
  font-size: 13px;
}

.current-tag {
  color: var(--lg-green) !important;
  border: 1px solid var(--lg-green);
  border-radius: 999px;
  padding: 1px 7px;
}

.stat {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.stat.add { color: var(--lg-green); }
.stat.remove { color: var(--lg-red); }

.version-actions button {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  padding: 4px 10px;
}
.version-actions button:hover {
  border-color: var(--link);
  color: var(--link);
}

.diff-box {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  max-height: 460px;
  overflow: auto;
}

.diff-row {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  min-height: 24px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 35%, transparent);
}

.line-no {
  padding: 3px 8px;
  background: color-mix(in srgb, var(--hover) 80%, transparent);
  color: var(--text-muted);
  text-align: right;
  user-select: none;
}

.diff-row code {
  padding: 3px 10px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
  color: var(--text);
}

.diff-row.add {
  background: color-mix(in srgb, var(--lg-green) 12%, transparent);
}
.diff-row.remove {
  background: color-mix(in srgb, var(--lg-red) 10%, transparent);
}
.diff-row.change {
  background: color-mix(in srgb, var(--lg-orange) 10%, transparent);
}

.diff-empty {
  padding: 8px 12px;
  color: var(--text-muted);
  background: var(--hover);
  font-family: inherit;
}

.full-text {
  border-top: 1px solid var(--border);
  padding: 16px 18px;
}

@media (max-width: 720px) {
  .version-head {
    align-items: stretch;
    flex-direction: column;
  }

  .version-actions button {
    flex: 1 1 auto;
  }
}
</style>
