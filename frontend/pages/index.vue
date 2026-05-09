<script setup lang="ts">
definePageMeta({ layout: 'default' })

const inputId = ref('')

function go(type: string) {
  if (!inputId.value.trim()) return
  navigateTo(`/${type}/${encodeURIComponent(inputId.value.trim())}`)
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
          placeholder="输入文章 ID / 剪贴板 ID / 用户 UID / 题号"
          @keydown.enter="go('article')"
        >
      </div>
      <div class="btn-group">
        <button @click="go('article')">文章</button>
        <button @click="go('paste')">剪贴板</button>
        <button @click="go('user')">用户</button>
        <button @click="go('problem')">题目</button>
      </div>
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
}
.btn-group {
  display: flex;
  gap: 8px;
  margin-top: 10px;
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
