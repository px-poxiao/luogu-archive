<script setup lang="ts">
const api = useApi()

const { data } = await useAsyncData('problem-list', () =>
  api<Record<string, Array<{ pid: string; title: string; difficulty: string | null; solution_open: boolean }>>>(
    '/problem/list',
  ),
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
  const keys = Object.keys(data.value)
  return keys.sort((a, b) => {
    const ai = diffOrder.indexOf(a)
    const bi = diffOrder.indexOf(b)
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
  })
})

const diffColor: Record<string, string> = {
  '入门': 'Red',
  '普及-': 'Orange',
  '普及/提高-': 'Orange',
  '普及+/提高': 'Green',
  '提高+/省选-': 'Blue',
  '省选/NOI-': 'Purple',
  'NOI/NOI+/CTSC': 'Black',
  '暂无评定': 'Gray',
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
    <h1>题目库（允许提交题解）</h1>
    <p class="note">
      按洛谷难度分档，仅显示**当前允许提交题解**的题目。
    </p>

    <section v-for="k in sortedKeys" :key="k" class="diff-section">
      <h2>
        <span class="lg-name" :data-color="diffColor[k] || 'Gray'">{{ k }}</span>
        <span class="count">{{ data![k].length }}</span>
      </h2>
      <ul class="problem-list">
        <li v-for="p in data![k]" :key="p.pid">
          <a :href="`https://www.luogu.com.cn/problem/${p.pid}`" target="_blank" rel="noopener">
            <span class="pid">{{ p.pid }}</span>
            <span class="title">{{ p.title }}</span>
          </a>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.note { color: var(--text-muted); }
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
}
.pid { color: var(--text-muted); font-family: monospace; }
.title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
