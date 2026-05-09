<script setup lang="ts">
const auth = useAuthStore()
const api = useApi()

const follows = ref<Array<{ uid: number; created_at: string }>>([])
const loading = ref(true)

onMounted(async () => {
  if (!auth.isLoggedIn) {
    navigateTo('/login')
    return
  }
  try {
    follows.value = await api('/follows')
  } catch (e: any) {
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <h1>我的关注</h1>
    <p class="muted" v-if="auth.isLoggedIn">
      登录邮箱：{{ auth.email }} · 已关注 {{ follows.length }} / 100
    </p>

    <div v-if="loading" class="loading">加载中...</div>
    <ul v-else-if="follows.length" class="list">
      <li v-for="f in follows" :key="f.uid">
        <NuxtLink :to="`/user/${f.uid}`">UID {{ f.uid }}</NuxtLink>
        <span class="time">关注于 {{ f.created_at }}</span>
      </li>
    </ul>
    <p v-else class="muted">还没关注任何洛谷用户。到用户主页点「关注」开始吧。</p>
  </div>
</template>

<style scoped>
.muted { color: var(--text-muted); }
.loading { padding: 20px; color: var(--text-muted); }
.list {
  list-style: none;
  padding: 0;
}
.list li {
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
}
.time { color: var(--text-muted); font-size: 13px; }
</style>
