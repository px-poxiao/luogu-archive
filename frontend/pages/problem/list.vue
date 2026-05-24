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

const { data } = await useAsyncData('problem-list', () =>
  api<Record<string, ProblemItem[]>>('/problem/list'),
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

const PREVIEW_LIMIT = 20

// 通过 ?difficulty=xxx 切到单档全列表视图
const selectedDiff = computed<string | null>(() => {
  const d = route.query.difficulty
  return typeof d === 'string' && d.length > 0 ? d : null
})

const visibleKeys = computed(() => {
  if (selectedDiff.value) {
    return sortedKeys.value.includes(selectedDiff.value) ? [selectedDiff.value] : []
  }
  return sortedKeys.value
})

function listFor(k: string): ProblemItem[] {
  const all = data.value?.[k] || []
  return selectedDiff.value ? all : all.slice(0, PREVIEW_LIMIT)
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

    <section v-for="k in visibleKeys" :key="k" class="diff-section">
      <h2>
        <span class="lg-name" :data-color="diffColor[k] || 'Gray'">{{ k }}</span>
        <span class="count">{{ data![k].length }}</span>
        <NuxtLink
          v-if="!selectedDiff && data![k].length > PREVIEW_LIMIT"
          :to="{ path: '/problem/list', query: { difficulty: k } }"
          class="view-all"
        >
          查看全部 →
        </NuxtLink>
      </h2>
      <ul class="problem-list">
        <li v-for="p in listFor(k)" :key="p.pid">
          <a :href="`https://www.luogu.com.cn/problem/${p.pid}`" target="_blank" rel="noopener">
            <span class="pid lg-name" :data-color="diffColor[k] || 'Gray'">{{ p.pid }}</span>
            <span class="title">{{ p.title }}</span>
          </a>
        </li>
      </ul>
      <p
        v-if="!selectedDiff && data![k].length > PREVIEW_LIMIT"
        class="more-hint"
      >
        仅显示前 {{ PREVIEW_LIMIT }} 道（共 {{ data![k].length }} 道），
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
