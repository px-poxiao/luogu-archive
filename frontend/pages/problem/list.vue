<script setup lang="ts">
const api = useApi()
const route = useRoute()
const { fromNow } = useTime()

interface ProblemItem {
  pid: string
  title: string
  difficulty: string | null
  tags: number[]
  solution_open: boolean
}

interface ProblemDifficultyBucket {
  items: ProblemItem[]
  total: number
}

const PREVIEW_LIMIT = 20

// 总览：每档前 20 条 + 该档总数
// 题目库接口较慢时不阻塞页面打开，先显示加载窗口。
const { data, pending: listPending } = useLazyAsyncData('problem-list', () =>
  api<Record<string, ProblemDifficultyBucket>>('/problem/list', {
    query: { preview_limit: PREVIEW_LIMIT },
  }),
  { server: false },
)
const { data: lastCrawled } = useLazyAsyncData('problem-list-last-crawled', () =>
  api<{ last_crawled_at: string | null }>('/last-crawled?type=problem_list'),
  { server: false },
)

const saveState = ref<'idle' | 'pending' | 'success' | 'failed' | 'cooldown' | 'captcha'>('idle')
const saveMessage = ref('')
const captchaToken = ref('')
const showCaptcha = ref(false)
const captchaRef = ref<any>(null)

const relTime = computed(() =>
  lastCrawled.value?.last_crawled_at ? fromNow(lastCrawled.value.last_crawled_at) : '未知',
)

async function saveProblemList() {
  if (saveState.value === 'pending') return
  saveState.value = 'pending'
  saveMessage.value = '排队中...'
  try {
    const resp = await api<{ task_id: string; merged: boolean; status: string }>('/save', {
      method: 'POST',
      body: {
        content_type: 'problem',
        id: 'list',
        captcha_token: captchaToken.value || undefined,
      },
    })
    showCaptcha.value = false
    captchaToken.value = ''
    captchaRef.value?.reset?.()
    saveState.value = 'success'
    saveMessage.value = resp.merged ? '已合并到进行中的任务' : '已派发，请稍后刷新'
    setTimeout(() => {
      saveState.value = 'idle'
      saveMessage.value = ''
    }, 3000)
  } catch (e: any) {
    const code = e?.data?.error_code
    if (code === 'captcha_required') {
      saveState.value = 'captcha'
      showCaptcha.value = true
      saveMessage.value = '请完成人机验证'
      await nextTick()
      try {
        captchaToken.value = await captchaRef.value?.getToken?.()
        await saveProblemList()
      } catch (err: any) {
        saveMessage.value = err?.message || '请先完成人机验证'
      }
    } else if (code === 'rate_limited') {
      saveState.value = 'cooldown'
      const s = e?.data?.data?.retry_after_sec || 30
      saveMessage.value = `冷却中 ${s}s`
      setTimeout(() => { saveState.value = 'idle' }, s * 1000)
    } else {
      saveState.value = 'failed'
      saveMessage.value = e?.data?.message || '失败'
      setTimeout(() => { saveState.value = 'idle' }, 3000)
    }
  }
}

// 按洛谷难度顺序排序
async function onCaptchaVerified(token: string) {
  if (saveState.value !== 'captcha') return
  captchaToken.value = token
  await saveProblemList()
}

const diffOrder = [
  '入门', '普及-', '普及', '普及+/提高-',
  '提高', '提高+/省选-', '省选/NOI-', 'NOI/NOI+/CTS',
  '暂无评定',
]
const sortedKeys = computed(() => {
  if (!data.value) return []
  return Object.keys(data.value).sort((a, b) => {
    const ai = diffOrder.indexOf(a)
    const bi = diffOrder.indexOf(b)
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
  })
})

const diffColor: Record<string, string> = {
  '入门': 'Red',
  '普及-': 'Orange',
  '普及': 'Yellow',
  '普及/提高-': 'Yellow',
  '普及+/提高-': 'Green',
  '普及+/提高': 'Green',
  '提高': 'Cyan',
  '提高+/省选-': 'Blue',
  '省选/NOI-': 'Purple',
  'NOI/NOI+/CTS': 'Black',
  'NOI/NOI+/CTSC': 'Black',
  'unknown_8': 'Black',
  '暂无评定': 'Gray',
}
// 通过 ?difficulty=xxx 切到单档全列表视图
const selectedDiff = computed<string | null>(() => {
  const d = route.query.difficulty
  return typeof d === 'string' && d.length > 0 ? d : null
})

// 单档全量数据：仅当 selectedDiff 非空时拉取，切换 query 时自动重拉
const { data: fullList, pending: fullPending } = useLazyAsyncData(
  'problem-list-full',
  () => {
    if (!selectedDiff.value) return Promise.resolve<ProblemItem[]>([])
    return api<ProblemItem[]>('/problem/list/by-difficulty', {
      query: { difficulty: selectedDiff.value },
    })
  },
  { server: false, watch: [selectedDiff] },
)

const visibleKeys = computed(() => {
  if (selectedDiff.value) {
    return sortedKeys.value.includes(selectedDiff.value) ? [selectedDiff.value] : []
  }
  return sortedKeys.value
})

function previewFor(k: string): ProblemItem[] {
  return data.value?.[k]?.items || []
}

function totalFor(k: string): number {
  return data.value?.[k]?.total || 0
}
</script>

<template>
  <div>
    <section class="problem-hero">
      <h1>题目库</h1>
      <div class="hero-meta">
        <span class="attr">
          <a href="https://www.luogu.com.cn/problem/list" target="_blank" rel="noopener noreferrer">
            查看洛谷原文
          </a>
          · 上次更新：{{ relTime }}
        </span>
        <button
          class="hero-save-btn"
          :class="{
            success: saveState === 'success',
            error: saveState === 'failed',
            cooldown: saveState === 'cooldown' || saveState === 'captcha',
          }"
          :disabled="saveState === 'pending'"
          @click="saveProblemList"
        >
          <span v-if="saveState === 'idle'">🔄 立即更新</span>
          <span v-else>{{ saveMessage }}</span>
        </button>
        <CaptchaChallenge
          v-if="showCaptcha"
          ref="captchaRef"
          id-suffix="problem-list-save"
          @verified="onCaptchaVerified"
        />
      </div>
    </section>
    <p v-if="selectedDiff" class="note diff-current">
      当前难度：
      <span class="lg-name" :data-color="diffColor[selectedDiff] || 'Gray'">{{ selectedDiff }}</span>
      · <NuxtLink to="/problem/list">← 返回所有难度</NuxtLink>
    </p>
    <p v-else class="note">
      允许提交题解的题目，按洛谷难度分档，每档仅显示前 {{ PREVIEW_LIMIT }} 道，点"查看全部"看完整列表。
    </p>

    <LoadingPanel
      v-if="listPending && !data"
      title="正在加载题目库"
      text="页面已经打开，正在读取题目和题解开放状态…"
    />

    <!-- 单档全量视图 -->
    <section v-else-if="selectedDiff" class="diff-section">
      <h2>
        <span class="lg-name" :data-color="diffColor[selectedDiff] || 'Gray'">{{ selectedDiff }}</span>
        <span class="count">{{ fullList?.length || 0 }}</span>
      </h2>
      <p v-if="fullPending" class="empty">加载中...</p>
      <ul v-else-if="fullList && fullList.length" class="problem-list">
        <li v-for="p in fullList" :key="p.pid">
          <a :href="`https://www.luogu.com.cn/problem/${p.pid}`" target="_blank" rel="noopener">
            <span class="pid lg-name" :data-color="diffColor[selectedDiff] || 'Gray'">{{ p.pid }}</span>
            <span class="title">{{ p.title }}</span>
          </a>
        </li>
      </ul>
      <p v-else class="empty">该档暂无题目</p>
    </section>

    <!-- 总览：所有难度的预览 -->
    <section v-for="k in visibleKeys" v-else :key="k" class="diff-section">
      <h2>
        <span class="lg-name" :data-color="diffColor[k] || 'Gray'">{{ k }}</span>
        <span class="count">{{ totalFor(k) }}</span>
        <NuxtLink
          v-if="totalFor(k) > PREVIEW_LIMIT"
          :to="{ path: '/problem/list', query: { difficulty: k } }"
          class="view-all"
        >
          查看全部 →
        </NuxtLink>
      </h2>
      <ul class="problem-list">
        <li v-for="p in previewFor(k)" :key="p.pid">
          <a :href="`https://www.luogu.com.cn/problem/${p.pid}`" target="_blank" rel="noopener">
            <span class="pid lg-name" :data-color="diffColor[k] || 'Gray'">{{ p.pid }}</span>
            <span class="title">{{ p.title }}</span>
          </a>
        </li>
      </ul>
      <p
        v-if="totalFor(k) > PREVIEW_LIMIT"
        class="more-hint"
      >
        仅显示前 {{ PREVIEW_LIMIT }} 道（共 {{ totalFor(k) }} 道），
        <NuxtLink :to="{ path: '/problem/list', query: { difficulty: k } }">
          查看该档全部题目 →
        </NuxtLink>
      </p>
    </section>
  </div>
</template>

<style scoped>
.problem-hero {
  position: relative;
  border-radius: 12px;
  padding: 22px 26px;
  margin-bottom: 20px;
  overflow: hidden;
  background: var(--hero-bg);
  border: 1px solid var(--hero-border);
}
.problem-hero h1 {
  margin: 0 0 10px;
  color: var(--hero-text);
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: 0.3px;
}
.hero-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.attr {
  flex: 1;
  min-width: 0;
  color: var(--hero-text-muted);
  font-size: 13.5px;
}
.attr a {
  color: var(--link);
  text-decoration: none;
}
.attr a:hover {
  text-decoration: underline;
}
.hero-save-btn {
  flex-shrink: 0;
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid var(--hero-border);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font-size: 13.5px;
  transition: background 0.15s, border-color 0.15s, transform 0.1s, color 0.15s;
}
.hero-save-btn:hover:not(:disabled) {
  border-color: var(--link);
  color: var(--link);
  transform: translateY(-1px);
}
.hero-save-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.hero-save-btn.success { color: var(--lg-green); border-color: var(--lg-green); }
.hero-save-btn.error { color: var(--lg-red); border-color: var(--lg-red); }
.hero-save-btn.cooldown { color: var(--lg-orange); border-color: var(--lg-orange); }
.note { color: var(--text-muted); }
.sub { font-size: 18px; font-weight: normal; margin-left: 4px; }
.diff-section {
  margin-bottom: 24px;
  min-width: 0;
}
.diff-section h2 {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}
.count {
  font-size: 13px;
  color: var(--text-muted);
  font-weight: normal;
}
.view-all {
  font-size: 13px;
  font-weight: normal;
  margin-left: auto;
}
.problem-list {
  list-style: none;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}
.problem-list li {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 10px;
  min-width: 0;
  box-sizing: border-box;
}
.problem-list a {
  color: var(--text);
  display: flex;
  gap: 10px;
  align-items: center;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}
.pid { font-family: monospace; font-weight: 600; }
.title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.more-hint {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

@media (max-width: 768px) {
  .problem-hero {
    padding: 18px 16px;
  }
  .problem-list {
    grid-template-columns: 1fr;
  }
  .view-all {
    margin-left: 0;
  }
}
</style>
