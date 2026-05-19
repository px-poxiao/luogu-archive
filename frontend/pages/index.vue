<script setup lang="ts">
definePageMeta({ layout: 'default' })

type JumpType = 'article' | 'paste' | 'user' | 'problem'

const inputId = ref('')
// 上次选择的跳转类型，写到 localStorage，下次回到首页保留选择
const selectedType = ref<JumpType>('article')

onMounted(() => {
  const saved = localStorage.getItem('quick-jump-type') as JumpType | null
  if (saved && ['article', 'paste', 'user', 'problem'].includes(saved)) {
    selectedType.value = saved
  }
})

function setType(t: JumpType) {
  selectedType.value = t
  if (process.client) localStorage.setItem('quick-jump-type', t)
}

function go(type?: JumpType) {
  const t = type || selectedType.value
  if (!inputId.value.trim()) return
  setType(t)
  navigateTo(`/${t}/${encodeURIComponent(inputId.value.trim())}`)
}

const TYPE_LABELS: Record<JumpType, string> = {
  article: '文章',
  paste: '剪贴板',
  user: '用户',
  problem: '题目',
}
</script>

<template>
  <div>
    <section class="hero">
      <h1>洛谷存档站</h1>
      <p class="subtitle">永久保存文章、剪贴板、犇犇、陶片放逐、题目信息</p>
    </section>

    <section class="quick-jump">
      <h2>快速跳转</h2>
      <div class="input-group">
        <input
          v-model="inputId"
          :placeholder="`输入 ${TYPE_LABELS[selectedType]} ID（回车跳转）`"
          @keydown.enter="go()"
        >
      </div>
      <div class="btn-group">
        <button
          v-for="t in (['article', 'paste', 'user', 'problem'] as JumpType[])"
          :key="t"
          :class="{ active: selectedType === t }"
          @click="go(t)"
        >{{ TYPE_LABELS[t] }}</button>
      </div>
      <p class="hint">点击类型按钮直接跳转；输入框回车跳到当前选中类型（{{ TYPE_LABELS[selectedType] }}）。</p>
    </section>

    <section class="quick-links">
      <h2>快速入口</h2>
      <div class="grid">
        <NuxtLink to="/feed" class="card">
          <h3>伪全网犇</h3>
          <p>全站最新犇犇墙</p>
        </NuxtLink>
        <NuxtLink to="/judgement" class="card">
          <h3>陶片放逐</h3>
          <p>封号公示存档</p>
        </NuxtLink>
        <NuxtLink to="/problem/list" class="card">
          <h3>题目库</h3>
          <p>按难度查看可提交题解的题目</p>
        </NuxtLink>
      </div>
    </section>
  </div>
</template>

<style scoped>
.hero {
  text-align: center;
  padding: 40px 0;
}
.hero h1 {
  font-size: 36px;
  margin: 0 0 8px;
}
.subtitle {
  color: var(--text-muted);
}
.quick-jump,
.quick-links {
  margin: 24px 0;
}
.input-group input {
  width: 100%;
  padding: 10px 14px;
  font-size: 16px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  box-sizing: border-box;
}
.btn-group {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}
.btn-group button {
  padding: 8px 16px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  border-radius: 6px;
  cursor: pointer;
}
.btn-group button:hover {
  border-color: var(--link);
  color: var(--link);
}
.btn-group button.active {
  border-color: var(--link);
  color: var(--link);
  background: color-mix(in srgb, var(--link) 8%, transparent);
}
.hint {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}
.card {
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
}
.card:hover {
  border-color: var(--link);
  text-decoration: none;
}
.card h3 {
  margin: 0 0 6px;
}
.card p {
  color: var(--text-muted);
  margin: 0;
}
</style>
