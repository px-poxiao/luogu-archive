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

onMounted(async () => {
  try { tags.value = await api<PluginTag[]>('/plugins/tags') } catch {}
  await load()
})

useHead({ title: '插件广场 - 洛谷档案馆' })
</script>

<template>
  <div class="plugin-market">
    <header class="market-hero">
      <div>
        <h1>插件广场</h1>
        <p>以已归档文章为原文，集中查看经管理组审核的插件代码与请求说明。</p>
      </div>
      <div class="hero-actions">
        <NuxtLink to="/plugin/manage" class="secondary-btn">我的插件</NuxtLink>
        <NuxtLink to="/plugin/submit" class="primary-btn">提交插件</NuxtLink>
      </div>
    </header>

    <section class="filters" aria-label="插件筛选">
      <select v-model="filters.tag_id" aria-label="功能标签">
        <option value="">全部标签</option>
        <option v-for="tag in tags" :key="tag.id" :value="String(tag.id)">{{ tag.name }}</option>
      </select>
      <select v-model="filters.request_level" aria-label="请求等级">
        <option value="">全部请求等级</option>
        <option value="0">无请求</option>
        <option value="1">少请求</option>
        <option value="2">中等请求</option>
        <option value="3">较多请求</option>
      </select>
      <select v-model="filters.runtime_mode" aria-label="运行方式">
        <option value="">全部运行方式</option>
        <option value="userscript">用户脚本</option>
        <option value="extension">浏览器扩展</option>
        <option value="bookmarklet">书签脚本</option>
        <option value="other">其他</option>
      </select>
      <select v-model="filters.device" aria-label="兼容设备">
        <option value="">全部设备</option>
        <option value="desktop">桌面端</option>
        <option value="mobile">移动端</option>
      </select>
      <select v-model="filters.badge" aria-label="可信度徽章">
        <option value="">全部徽章</option>
        <option value="official">官方插件</option>
        <option value="recommended">推荐插件</option>
      </select>
      <select v-model="filters.updated_days" aria-label="最近更新时间">
        <option value="">全部更新时间</option>
        <option value="7">最近 7 天</option>
        <option value="30">最近 30 天</option>
        <option value="90">最近 90 天</option>
      </select>
      <button type="button" @click="applyFilters">筛选</button>
    </section>

    <LoadingPanel v-if="loading" title="loading……" text="" />
    <div v-else-if="errorText" class="state-box error">{{ errorText }}</div>
    <div v-else-if="rows.length" class="plugin-grid">
      <NuxtLink v-for="row in rows" :key="row.article_id" :to="`/plugin/${row.article_id}`" class="plugin-card">
        <div class="card-head">
          <div>
            <h2>{{ row.article_title }}</h2>
          </div>
          <PluginRequestLevelBadge :level="row.final_request_level" compact />
        </div>
        <p class="summary">{{ row.summary }}</p>
        <div class="badges">
          <span v-if="row.is_official" class="trust official">官方插件</span>
          <span v-if="row.is_recommended" class="trust recommended">推荐插件</span>
          <span v-for="tag in row.tags" :key="tag.id" class="tag">{{ tag.name }}</span>
        </div>
        <footer>
          <span v-if="row.article_author">文章作者：<LuoguUserName :user="row.article_author" no-link /></span>
          <span>v{{ row.version }} · {{ runtimeMode(row.runtime_mode) }}</span>
          <span>更新于 {{ format(row.updated_at) }}</span>
        </footer>
      </NuxtLink>
    </div>
    <div v-else class="state-box">没有符合条件的插件</div>

    <nav v-if="total > 20" class="pagination" aria-label="分页">
      <button type="button" :disabled="page <= 1" @click="page--; load()">上一页</button>
      <span>第 {{ page }} 页，共 {{ Math.ceil(total / 20) }} 页</span>
      <button type="button" :disabled="page * 20 >= total" @click="page++; load()">下一页</button>
    </nav>
  </div>
</template>

<style scoped>
.plugin-market { display: grid; gap: 22px; }
.market-hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 140px; padding: 26px 30px; box-sizing: border-box; border: 1px solid var(--hero-border); border-radius: 8px; background: var(--hero-bg); }
.market-hero h1 { margin: 0; font-size: 30px; }
.market-hero p { margin: 8px 0 0; color: var(--hero-text-muted); }
.hero-actions { display: flex; gap: 10px; flex-shrink: 0; }
.primary-btn, .secondary-btn { display: inline-flex; align-items: center; min-height: 38px; padding: 0 15px; border-radius: 6px; text-decoration: none; }
.primary-btn { background: var(--link); color: #fff; }
.secondary-btn { border: 1px solid var(--border); background: var(--surface); color: var(--text); }
.filters { display: grid; grid-template-columns: repeat(3, minmax(120px, 1fr)) repeat(3, minmax(110px, .85fr)) auto; gap: 10px; }
.filters select, .filters button { min-width: 0; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); padding: 8px 10px; font: inherit; }
.filters button { padding-inline: 18px; background: var(--link); color: #fff; cursor: pointer; }
.plugin-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.plugin-card { display: grid; align-content: start; gap: 14px; min-width: 0; padding: 18px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); text-decoration: none; transition: border-color .15s, transform .15s; }
.plugin-card:hover { border-color: var(--link); transform: translateY(-1px); text-decoration: none; }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.card-head h2 { margin: 0; font-size: 20px; }
.summary { margin: 0; min-height: 3.2em; color: var(--text-muted); }
.badges { display: flex; flex-wrap: wrap; gap: 7px; }
.trust, .tag { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.official { background: var(--lg-blue); color: #fff; }
.recommended { background: var(--lg-yellow); color: #332800; }
.tag { border: 1px solid var(--border); color: var(--text-muted); }
.plugin-card footer { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 12px; border-top: 1px solid var(--border); padding-top: 12px; color: var(--text-muted); font-size: 13px; }
.state-box { padding: 42px 18px; border: 1px solid var(--border); text-align: center; color: var(--text-muted); }
.state-box.error { color: var(--lg-red); }
.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; }
.pagination button { border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); padding: 7px 12px; cursor: pointer; }
.pagination button:disabled { opacity: .45; cursor: default; }
@media (max-width: 980px) { .filters { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 720px) {
  .market-hero { align-items: flex-start; flex-direction: column; padding: 22px 18px; }
  .market-hero h1 { font-size: 25px; }
  .filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .plugin-grid { grid-template-columns: 1fr; }
  .plugin-card footer { flex-direction: column; }
}
</style>
