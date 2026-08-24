<script setup lang="ts">
import type { PluginTag } from '~/types/plugin'

const api = useApi()
const { runtimeMode } = usePluginLabels()
const { format } = useTime()

const tags = ref<PluginTag[]>([])
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const errorText = ref('')
const filters = reactive({
  tag_id: '',
  request_level: '',
  runtime_mode: '',
  device: '',
  badge: '',
  updated_days: '',
})

const activeTagName = computed(() => {
  if (!filters.tag_id) return '全部插件'
  return tags.value.find(tag => String(tag.id) === filters.tag_id)?.name || '筛选结果'
})

const hasFilters = computed(() => Object.values(filters).some(Boolean))

function displaySummary(value: unknown) {
  const chars = Array.from(String(value || '').trim())
  return chars.length <= 50 ? chars.join('') : `${chars.slice(0, 49).join('')}…`
}

async function load() {
  loading.value = true
  errorText.value = ''
  try {
    const query: Record<string, string | number | boolean> = { page: page.value, page_size: 20 }
    if (filters.tag_id) query.tag_id = filters.tag_id
    if (filters.request_level !== '') query.request_level = filters.request_level
    if (filters.runtime_mode) query.runtime_mode = filters.runtime_mode
    if (filters.device) query.device = filters.device
    if (filters.badge === 'official') query.official = true
    if (filters.badge === 'recommended') query.recommended = true
    if (filters.updated_days) query.updated_within_days = filters.updated_days
    const data = await api<any>('/plugins', { query })
    rows.value = data.items
    total.value = data.total
  } catch (error: any) {
    errorText.value = error?.data?.message || '插件列表加载失败'
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  void load()
}

function selectTag(tagId: string) {
  filters.tag_id = tagId
  applyFilters()
}

function resetFilters() {
  Object.assign(filters, {
    tag_id: '',
    request_level: '',
    runtime_mode: '',
    device: '',
    badge: '',
    updated_days: '',
  })
  applyFilters()
}

onMounted(async () => {
  try { tags.value = await api<PluginTag[]>('/plugins/tags') } catch {}
  await load()
})

useHead({ title: '插件广场 - 洛谷档案馆' })
</script>

<template>
  <div class="plugin-market">
    <header class="market-heading">
      <div>
        <h1>插件广场</h1>
        <p>浏览经管理组审核的洛谷插件与请求说明</p>
      </div>
      <div class="hero-actions">
        <NuxtLink to="/plugin/manage" class="archive-action-button">我的插件</NuxtLink>
        <NuxtLink to="/plugin/submit" class="archive-action-button">提交插件</NuxtLink>
      </div>
    </header>

    <div class="market-shell">
      <aside class="filter-sidebar" aria-label="插件筛选">
        <div class="sidebar-title">功能标签</div>
        <div class="tag-options">
          <button
            type="button"
            class="tag-option all-option"
            :class="{ active: !filters.tag_id }"
            @click="selectTag('')"
          >
            <span class="tag-dot" />
            全部插件
          </button>
          <button
            v-for="(tag, index) in tags"
            :key="tag.id"
            type="button"
            class="tag-option"
            :class="[{ active: filters.tag_id === String(tag.id) }, `tag-color-${index % 6}`]"
            @click="selectTag(String(tag.id))"
          >
            <span class="tag-dot" />
            {{ tag.name }}
          </button>
        </div>

        <div class="filter-fields">
          <label>
            <span>请求等级</span>
            <select v-model="filters.request_level">
              <option value="">全部等级</option>
              <option value="0">无请求</option>
              <option value="1">少请求</option>
              <option value="2">中等请求</option>
              <option value="3">较多请求</option>
            </select>
          </label>
          <label>
            <span>运行方式</span>
            <select v-model="filters.runtime_mode">
              <option value="">全部方式</option>
              <option value="userscript">用户脚本</option>
              <option value="extension">浏览器扩展</option>
              <option value="bookmarklet">书签脚本</option>
              <option value="other">其他</option>
            </select>
          </label>
          <label>
            <span>兼容设备</span>
            <select v-model="filters.device">
              <option value="">全部设备</option>
              <option value="desktop">桌面端</option>
              <option value="mobile">移动端</option>
            </select>
          </label>
          <label>
            <span>可信徽章</span>
            <select v-model="filters.badge">
              <option value="">全部徽章</option>
              <option value="official">官方插件</option>
              <option value="recommended">推荐插件</option>
            </select>
          </label>
          <label>
            <span>更新时间</span>
            <select v-model="filters.updated_days">
              <option value="">不限时间</option>
              <option value="7">最近 7 天</option>
              <option value="30">最近 30 天</option>
              <option value="90">最近 90 天</option>
            </select>
          </label>
        </div>

        <div class="filter-actions">
          <button type="button" class="archive-action-button" @click="applyFilters">应用筛选</button>
          <button v-if="hasFilters" type="button" class="archive-action-button" @click="resetFilters">清除筛选</button>
        </div>
      </aside>

      <main class="results-pane">
        <header class="results-heading">
          <div>
            <h2>{{ activeTagName }}</h2>
            <span v-if="!loading">{{ total }} 个插件</span>
          </div>
          <span class="sort-label">按最近更新排列</span>
        </header>

        <LoadingPanel v-if="loading" title="loading……" text="" />
        <div v-else-if="errorText" class="state-box error">{{ errorText }}</div>
        <div v-else-if="rows.length" class="plugin-list">
          <article v-for="row in rows" :key="row.article_id" class="plugin-row">
            <div class="row-heading">
              <NuxtLink :to="`/plugin/${row.article_id}`" class="plugin-title">
                {{ row.article_title }}
              </NuxtLink>
              <PluginRequestLevelBadge :level="row.final_request_level" compact />
            </div>

            <p v-if="row.summary" class="summary">{{ displaySummary(row.summary) }}</p>

            <div class="row-meta">
              <span v-if="row.article_author" class="article-author">
                <NuxtLink :to="`/user/${row.article_author.uid}`" class="author-avatar" tabindex="-1" aria-hidden="true">
                  <img v-if="row.article_author.avatar" :src="row.article_author.avatar" alt="" loading="lazy">
                  <span v-else :data-color="row.article_author.color">{{ (row.article_author.name || '?').charAt(0).toUpperCase() }}</span>
                </NuxtLink>
                <LuoguUserName :user="row.article_author" show-badge />
              </span>
              <span class="meta-item">{{ runtimeMode(row.runtime_mode) }}</span>
              <span class="meta-item">更新于 {{ format(row.updated_at) }}</span>
              <span class="meta-item" v-if="row.total_usage !== undefined">使用次数 {{ row.total_usage }}</span>
            </div>

            <footer class="row-footer">
              <div class="badges">
                <span v-if="row.is_official" class="trust official">官方插件</span>
                <span v-if="row.is_recommended" class="trust recommended">推荐插件</span>
                <span v-for="tag in row.tags" :key="tag.id" class="tag">{{ tag.name }}</span>
              </div>
              <NuxtLink :to="`/plugin/${row.article_id}`" class="detail-link">查看插件</NuxtLink>
            </footer>
          </article>
        </div>
        <div v-else class="state-box">没有符合条件的插件</div>

        <nav v-if="total > 20" class="pagination" aria-label="分页">
          <button type="button" class="archive-action-button" :disabled="page <= 1" @click="page--; load()">上一页</button>
          <span>第 {{ page }} 页，共 {{ Math.ceil(total / 20) }} 页</span>
          <button type="button" class="archive-action-button" :disabled="page * 20 >= total" @click="page++; load()">下一页</button>
        </nav>
      </main>
    </div>
  </div>
</template>

<style scoped>
.plugin-market { display: grid; gap: 18px; }
.market-heading { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 112px; padding: 22px 26px; box-sizing: border-box; border: 1px solid var(--hero-border); border-radius: 8px; background: var(--hero-bg); }
.market-heading h1 { margin: 0; font-size: 28px; }
.market-heading p { margin: 6px 0 0; color: var(--hero-text-muted); }
.hero-actions { display: flex; gap: 10px; flex-shrink: 0; }

.market-shell { display: grid; grid-template-columns: minmax(215px, 250px) minmax(0, 1fr); align-items: start; gap: 18px; }
.filter-sidebar { position: sticky; top: 18px; display: grid; gap: 18px; padding: 18px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
.sidebar-title { font-size: 17px; font-weight: 700; }
.tag-options { display: grid; gap: 3px; }
.tag-option { display: flex; align-items: center; gap: 9px; width: 100%; min-height: 35px; padding: 6px 8px; border: 0; border-radius: 4px; background: transparent; color: var(--text); font: inherit; text-align: left; cursor: pointer; }
.tag-option:hover { background: var(--hover); }
.tag-option.active { background: color-mix(in srgb, var(--link) 11%, var(--surface)); color: var(--link); font-weight: 600; }
.tag-dot { width: 11px; height: 11px; flex: 0 0 11px; border-radius: 2px; background: var(--lg-blue); }
.all-option .tag-dot { background: var(--text); }
.tag-color-1 .tag-dot { background: var(--lg-orange); }
.tag-color-2 .tag-dot { background: var(--lg-purple); }
.tag-color-3 .tag-dot { background: var(--lg-green); }
.tag-color-4 .tag-dot { background: var(--lg-cyan); }
.tag-color-5 .tag-dot { background: var(--lg-red); }
.filter-fields { display: grid; gap: 12px; padding-top: 16px; border-top: 1px solid var(--border); }
.filter-fields label { display: grid; gap: 5px; color: var(--text-muted); font-size: 13px; }
.filter-fields select { width: 100%; min-width: 0; border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--text); padding: 8px 9px; font: inherit; }
.filter-actions { display: grid; gap: 8px; }
.filter-actions .archive-action-button { width: 100%; min-height: 36px; }

.results-pane { min-width: 0; }
.results-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 46px; margin-bottom: 12px; padding: 0 2px; }
.results-heading > div { display: flex; align-items: baseline; gap: 10px; }
.results-heading h2 { margin: 0; font-size: 21px; }
.results-heading span { color: var(--text-muted); font-size: 13px; }
.sort-label { white-space: nowrap; }
.plugin-list { display: grid; gap: 12px; }
.plugin-row { display: grid; gap: 11px; min-width: 0; padding: 18px 20px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); transition: border-color .15s, box-shadow .15s; }
.plugin-row:hover { border-color: color-mix(in srgb, var(--link) 48%, var(--border)); box-shadow: 0 3px 12px color-mix(in srgb, var(--text) 6%, transparent); }
.row-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.plugin-title { min-width: 0; color: var(--text); font-size: 20px; font-weight: 600; line-height: 1.4; text-decoration: none; overflow-wrap: anywhere; }
.plugin-title:hover { color: var(--link); text-decoration: none; }
.summary { margin: 0; color: var(--text-muted); line-height: 1.65; overflow-wrap: anywhere; }
.row-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 7px 14px; color: var(--text-muted); font-size: 13px; }
.article-author { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
.author-avatar { display: inline-flex; flex: 0 0 34px; width: 34px; height: 34px; border-radius: 50%; overflow: hidden; text-decoration: none; }
.author-avatar img, .author-avatar > span { width: 100%; height: 100%; }
.author-avatar img { display: block; object-fit: cover; background: var(--bg); }
.author-avatar > span { display: grid; place-items: center; background: var(--lg-gray); color: #fff; font-weight: 600; }
.author-avatar > span[data-color="Blue"] { background: var(--lg-blue); }
.author-avatar > span[data-color="Green"] { background: var(--lg-green); }
.author-avatar > span[data-color="Orange"] { background: var(--lg-orange); }
.author-avatar > span[data-color="Red"] { background: var(--lg-red); }
.author-avatar > span[data-color="Purple"] { background: var(--lg-purple); }
.author-avatar > span[data-color="Cyan"] { background: var(--lg-cyan); }
.author-avatar > span[data-color="Black"] { background: var(--lg-black); }
.author-avatar > span[data-color="Cheater"] { background: var(--lg-cheater-tag); }
.meta-item { white-space: nowrap; }
.row-footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding-top: 2px; }
.badges { display: flex; flex-wrap: wrap; gap: 7px; }
.trust, .tag { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.official { background: var(--lg-blue); color: #fff; }
.recommended { background: var(--lg-yellow); color: #332800; }
.tag { border: 1px solid var(--border); color: var(--text-muted); }
.detail-link { flex-shrink: 0; white-space: nowrap; font-size: 14px; }
.state-box { padding: 42px 18px; border: 1px solid var(--border); text-align: center; color: var(--text-muted); }
.state-box.error { color: var(--lg-red); }
.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; margin-top: 18px; }

@media (max-width: 860px) {
  .market-shell { grid-template-columns: 1fr; }
  .filter-sidebar { position: static; }
  .tag-options { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .filter-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filter-actions { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  .market-heading { align-items: flex-start; flex-direction: column; padding: 20px 17px; }
  .market-heading h1 { font-size: 24px; }
  .hero-actions { width: 100%; }
  .hero-actions .archive-action-button { flex: 1; }
  .filter-sidebar { padding: 15px; }
  .tag-options, .filter-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .plugin-row { padding: 16px; }
  .row-heading { align-items: flex-start; flex-direction: column; gap: 8px; }
  .plugin-title { font-size: 18px; }
  .row-footer { align-items: flex-start; flex-direction: column; }
  .detail-link { align-self: flex-end; }
  .results-heading { align-items: flex-start; }
  .sort-label { display: none; }
}
@media (max-width: 390px) {
  .tag-options, .filter-fields { grid-template-columns: 1fr; }
}
</style>
