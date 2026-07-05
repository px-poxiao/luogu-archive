<script setup lang="ts">
type CardKind = 'activity' | 'random'

const route = useRoute()
const api = useApi()
const uid = String(route.params.uid || '')
const selected = ref<CardKind>('activity')
const copied = ref<'link' | 'markdown' | null>(null)
const imageNonce = ref(Date.now())

interface UserProfile {
  uid: number
  name: string
  avatar: string | null
  badge: string | null
  color: string
  ccf_level: number
  xcpc_level: number
  is_admin: boolean
  name_hidden: boolean
}

const { data: profile, pending, error } = useLazyAsyncData(
  `user-card-${uid}`,
  () => api<UserProfile>(`/user/${uid}`),
  { server: false },
)

const pageTitle = computed(() => {
  const name = profile.value?.name_hidden ? `UID ${profile.value.uid}` : profile.value?.name
  return name ? `${name} 的图卡` : '图卡预览'
})

const cardPath = computed(() => `/api/v1/image/feed/${selected.value}/${uid}.svg`)
const imageUrl = computed(() => {
  if (!import.meta.client) return cardPath.value
  return `${window.location.origin}${cardPath.value}`
})
const previewSrc = computed(() => `${cardPath.value}?t=${imageNonce.value}`)
const markdown = computed(() => {
  // 嵌入用 Markdown 保持最短格式，避免把用户名和图卡类型带到正文里。
  return `![](${imageUrl.value})`
})

const cardKinds: Array<{ key: CardKind; label: string }> = [
  { key: 'activity', label: '活跃统计' },
  { key: 'random', label: '随机语录' },
]

async function copyText(kind: 'link' | 'markdown') {
  const text = kind === 'link' ? imageUrl.value : markdown.value
  await navigator.clipboard.writeText(text)
  copied.value = kind
  setTimeout(() => { copied.value = null }, 1400)
}

function refreshPreview() {
  imageNonce.value = Date.now()
}
</script>

<template>
  <LoadingPanel v-if="pending" title="正在加载图卡" text="正在读取用户资料..." />

  <div v-else-if="error" class="error-box">
    <h2>{{ error.data?.message || '用户未收录' }}</h2>
    <p>稍后刷新页面即可重试。</p>
  </div>

  <div v-else class="card-page">
    <div class="page-head">
      <div>
        <NuxtLink :to="`/user/${uid}`" class="back-link">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 18l-6-6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
          返回用户主页
        </NuxtLink>
        <h1>{{ pageTitle }}</h1>
        <p>预览 SVG 图卡，并复制可嵌入链接。</p>
      </div>
      <button type="button" class="ghost-btn" @click="refreshPreview">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 11-2.6-6.4M21 4v6h-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
        刷新预览
      </button>
    </div>

    <div class="preview-grid">
      <section class="preview-panel">
        <div class="preview-shell" :class="selected">
          <img :src="previewSrc" :alt="selected === 'activity' ? '活跃统计图卡预览' : '随机语录图卡预览'">
        </div>
      </section>

      <aside class="side-panel">
        <section class="panel-section">
          <h2>图卡类型</h2>
          <div class="segmented" role="tablist" aria-label="图卡类型">
            <button
              v-for="item in cardKinds"
              :key="item.key"
              type="button"
              :class="{ active: selected === item.key }"
              @click="selected = item.key; refreshPreview()"
            >{{ item.label }}</button>
          </div>
        </section>

        <section class="panel-section">
          <h2>图片链接</h2>
          <div class="copy-row">
            <input :value="imageUrl" readonly>
            <button type="button" @click="copyText('link')">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 8h10v12H8zM6 16H4V4h12v2" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" /></svg>
              {{ copied === 'link' ? '已复制' : '复制' }}
            </button>
          </div>
        </section>

        <section class="panel-section">
          <h2>Markdown</h2>
          <textarea :value="markdown" readonly rows="5" />
          <button type="button" class="full-btn" @click="copyText('markdown')">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 8h10v12H8zM6 16H4V4h12v2" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" /></svg>
            {{ copied === 'markdown' ? '已复制 Markdown' : '复制 Markdown' }}
          </button>
        </section>

        <a :href="cardPath" target="_blank" rel="noopener noreferrer" class="open-link">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7M21 3l-9 9M19 14v5H5V5h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
          打开图片
        </a>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.card-page {
  display: grid;
  gap: 20px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
}
.page-head h1 {
  margin: 12px 0 6px;
  font-size: 28px;
  line-height: 1.25;
}
.page-head p {
  margin: 0;
  color: var(--text-muted);
}
.back-link,
.open-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 14px;
}
.back-link:hover,
.open-link:hover {
  color: var(--link);
  text-decoration: none;
}
.back-link svg,
.open-link svg,
.ghost-btn svg,
.copy-row button svg,
.full-btn svg {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
}
.ghost-btn,
.full-btn,
.copy-row button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  min-height: 38px;
  padding: 0 13px;
}
.ghost-btn:hover,
.full-btn:hover,
.copy-row button:hover {
  border-color: var(--link);
  color: var(--link);
}
.preview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 20px;
  align-items: start;
}
.preview-panel,
.side-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.preview-panel {
  padding: 22px;
}
.preview-shell {
  display: grid;
  place-items: center;
  min-height: 460px;
  padding: 24px;
  border-radius: 8px;
  background:
    linear-gradient(45deg, rgba(148, 163, 184, 0.10) 25%, transparent 25%),
    linear-gradient(-45deg, rgba(148, 163, 184, 0.10) 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, rgba(148, 163, 184, 0.10) 75%),
    linear-gradient(-45deg, transparent 75%, rgba(148, 163, 184, 0.10) 75%);
  background-size: 22px 22px;
  background-position: 0 0, 0 11px, 11px -11px, -11px 0;
}
.preview-shell img {
  display: block;
  width: 100%;
  height: auto;
  max-height: 100%;
  object-fit: contain;
}
.preview-shell.random img {
  max-width: 900px;
}
.side-panel {
  padding: 18px;
  display: grid;
  gap: 20px;
}
.panel-section {
  display: grid;
  gap: 10px;
}
.panel-section h2 {
  margin: 0;
  font-size: 15px;
  color: var(--text-muted);
}
.segmented {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
}
.segmented button {
  border: 0;
  border-radius: 6px;
  padding: 8px 10px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font: inherit;
}
.segmented button.active {
  background: var(--surface);
  color: var(--link);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.copy-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}
input,
textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
  font: 13px/1.6 ui-monospace, SFMono-Regular, Consolas, monospace;
}
input {
  min-height: 38px;
  padding: 0 10px;
}
textarea {
  resize: vertical;
  min-height: 108px;
  padding: 10px;
}
.full-btn {
  width: 100%;
}
.open-link {
  justify-content: center;
  min-height: 40px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.error-box {
  padding: 30px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  text-align: center;
}
@media (max-width: 980px) {
  .page-head,
  .preview-grid {
    grid-template-columns: 1fr;
    display: grid;
  }
  .preview-grid {
    gap: 14px;
  }
  .side-panel {
    order: -1;
  }
}
@media (max-width: 640px) {
  .preview-panel,
  .side-panel {
    border-radius: 0;
    margin-inline: calc(var(--page-gutter) * -1);
  }
  .preview-panel {
    padding: 12px;
  }
  .preview-shell {
    min-height: 260px;
    padding: 10px;
  }
  .copy-row {
    grid-template-columns: 1fr;
  }
}
</style>
