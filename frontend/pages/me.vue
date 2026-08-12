<script setup lang="ts">
const auth = useAuthStore()
const api = useApi()

const follows = ref<Array<{ uid: number; created_at: string }>>([])
interface MeData {
  email: string
  display_name: string
  follow_count: number
  luogu_uid: number | null
  luogu_bound_at: string | null
}

const me = ref<MeData | null>(null)
const loading = ref(true)

function handleBound(uid: number) {
  if (me.value) me.value.luogu_uid = uid
}

onMounted(async () => {
  if (!auth.isLoggedIn) {
    navigateTo('/login')
    return
  }
  try {
    const [followRows, meData] = await Promise.all([
      api<Array<{ uid: number; created_at: string }>>('/follows'),
      api<MeData>('/auth/me'),
    ])
    follows.value = followRows
    me.value = meData
  } catch (e: any) {
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <PageHero title="我的关注" />
    <section v-if="auth.isLoggedIn" class="account-bar">
      <div>
        <strong>{{ me?.display_name || auth.displayName }}</strong>
        <p>登录邮箱：{{ me?.email || auth.email }} · 已关注 {{ follows.length }} / 100</p>
      </div>
      <LuoguBindButton
        v-if="me"
        :luogu-uid="me?.luogu_uid ?? null"
        @bound="handleBound"
      />
    </section>

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
.account-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 20px;
  padding: 15px 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}
.account-bar strong { font-size: 16px; }
.account-bar p { margin: 2px 0 0; color: var(--text-muted); font-size: 14px; }
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
@media (max-width: 620px) {
  .account-bar { align-items: flex-start; flex-direction: column; }
}
</style>
