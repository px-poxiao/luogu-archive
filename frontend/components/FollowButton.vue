<!--
  关注按钮。挂在用户主页上。
  - 未登录：点击跳登录
  - 已关注：显示"取消关注"
  - 未关注：显示"关注"
-->
<script setup lang="ts">
const props = defineProps<{ uid: number }>()

const auth = useAuthStore()
const api = useApi()
const following = ref(false)
const loading = ref(false)

async function refresh() {
  if (!auth.isLoggedIn) return
  try {
    const list = await api<Array<{ uid: number }>>('/follows')
    following.value = list.some(r => r.uid === props.uid)
  } catch {}
}

onMounted(refresh)
watch(() => auth.isLoggedIn, refresh)

async function toggle() {
  if (!auth.isLoggedIn) {
    navigateTo('/login')
    return
  }
  loading.value = true
  try {
    if (following.value) {
      await api(`/follows/${props.uid}`, { method: 'DELETE' })
      following.value = false
    } else {
      await api('/follows', { method: 'POST', body: { uid: props.uid } })
      following.value = true
    }
  } catch (e: any) {
    alert(e?.data?.message || '操作失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <button
    class="follow-btn"
    :class="{ following }"
    :disabled="loading"
    @click="toggle"
  >
    <span v-if="!auth.isLoggedIn">关注（需登录）</span>
    <span v-else-if="following">✓ 已关注（取消）</span>
    <span v-else>+ 关注</span>
  </button>
</template>

<style scoped>
.follow-btn {
  padding: 6px 16px;
  border-radius: 16px;
  border: 1px solid var(--link);
  background: var(--link);
  color: white;
  cursor: pointer;
  font-size: 14px;
}
.follow-btn.following {
  background: var(--surface);
  color: var(--link);
}
.follow-btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
