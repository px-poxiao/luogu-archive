<script setup lang="ts">
// 邮箱验证落地页。用户从邮件里点 {WEB_PUBLIC_ORIGIN}/auth/verify?token=xxx 进来，
// 这里读 token 调后端 /auth/verify 完成验证，再引导去登录。
const route = useRoute()
const api = useApi()

const state = ref<'loading' | 'success' | 'error'>('loading')
const message = ref('')

onMounted(async () => {
  const token = route.query.token
  if (typeof token !== 'string' || !token) {
    state.value = 'error'
    message.value = '验证链接缺少参数，请检查邮件里的完整链接'
    return
  }
  try {
    const resp = await api<{ message: string }>('/auth/verify', {
      query: { token },
    })
    state.value = 'success'
    message.value = resp.message || '邮箱验证成功'
  } catch (e: any) {
    state.value = 'error'
    message.value = e?.data?.message || '验证失败，链接可能已失效'
  }
})
</script>

<template>
  <div class="wrap">
    <h1>邮箱验证</h1>

    <div v-if="state === 'loading'" class="box loading">
      <p>正在验证，请稍候...</p>
    </div>

    <div v-else-if="state === 'success'" class="box success">
      <h2>✓ {{ message }}</h2>
      <p>现在可以登录了。</p>
      <NuxtLink to="/login" class="btn">前往登录</NuxtLink>
    </div>

    <div v-else class="box error">
      <h2>✗ 验证未成功</h2>
      <p>{{ message }}</p>
      <NuxtLink to="/register" class="btn">重新注册</NuxtLink>
    </div>
  </div>
</template>

<style scoped>
.wrap { max-width: 420px; margin: 40px auto; }
.box {
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  margin-top: 16px;
}
.box.success { border-color: var(--lg-green); }
.box.success h2 { color: var(--lg-green); margin-top: 0; }
.box.error { border-color: var(--lg-red); }
.box.error h2 { color: var(--lg-red); margin-top: 0; }
.box.loading { color: var(--text-muted); }
.btn {
  display: inline-block;
  margin-top: 12px;
  padding: 10px 20px;
  background: var(--link);
  color: white;
  border-radius: 6px;
  text-decoration: none;
}
</style>
