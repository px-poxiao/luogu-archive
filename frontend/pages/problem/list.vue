<script setup lang="ts">
const api = useApi()
const route = useRoute()

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
const { data } = await useAsyncData('problem-list', () =>
  api<Record<string, ProblemDifficultyBucket>>('/problem/list', {
    query: { preview_limit: PREVIEW_LIMIT },
  }),
)
const { data: lastCrawled } = await useAsyncData('problem-list-last-crawled', () =>
  api<{ last_crawled_at: string | null }>('/last-crawled?type=problem_list'),
)

// 按洛谷难度顺序排序
const diffOrder = [
  '入门', '普及-', '普及/提高-', '普及+/提高',
  '提高+/省选-', '省选/NOI-', 'NOI/NOI+/CTSC',
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
  '普及/提高-': 'Yellow',
  '普及+/提高': 'Green',
  '提高+/省选-': 'Blue',
  '省选/NOI-': 'Purple',
  'NOI/NOI+/CTSC': 'Black',
  '暂无评定': 'Gray',
}

// 通过 ?difficulty=xxx 切到单档全列表视图
const selectedDiff = computed<string | null>(() => {
  const d = route.query.difficulty
  return typeof d === 'string' && d.length > 0 ? d : null
})

// 单档全量数据：仅当 selectedDiff 非空时拉取，切换 query 时自动重拉
const { data: fullList, pending: fullPending } = await useAsyncData(
  'problem-list-full',
  () => {
    if (!selectedDiff.value) return Promise.resolve<ProblemItem[]>([])
    return api<ProblemItem[]>('/problem/list/by-difficulty', {
      query: { difficulty: selectedDiff.value },
    })
  },
  { watch: [selectedDiff] },
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
    <OriginBanner
      origin-url="https://www.luogu.com.cn/problem/list"
      :crawled-at="lastCrawled?.last_crawled_at"
      content-type="problem"
      content-id="list"
    />
    <h1>
      题目库（允许提交题解）
      <span v-if="selectedDiff" class="sub">
        ·
        <span class="lg-name" :data-color="diffColor[selectedDiff] || 'Gray'">{{ selectedDiff }}</span>
      </span>
    </h1>
    <p v-if="!selectedDiff" class="note">
      按洛谷难度分档，每档仅显示前 {{ PREVIEW_LIMIT }} 道，点"查看全部"看完整列表。
    </p>
    <p v-else class="note">
      <NuxtLink to="/problem/list">← 返回所有难度</NuxtLink>
    </p>

    <!-- 单档全量视图 -->
    <section v-if="selectedDiff" class="diff-section">
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
.note { color: var(--text-muted); }
.sub { font-size: 18px; font-weight: normal; margin-left: 4px; }
.diff-section {
  margin-bottom: 24px;
}
.diff-section h2 {
  display: flex;
  align-items: center;
  gap: 10px;
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
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 6px;
}
.problem-list li {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 10px;
}
.problem-list a {
  color: var(--text);
  display: flex;
  gap: 10px;
  align-items: center;
}
.pid { font-family: monospace; font-weight: 600; }
.title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.more-hint {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}
</style>
