<script setup lang="ts">
const form = ref({ email: '', password: '' })
const err = ref('')
const loading = ref(false)

const api = useApi()
const auth = useAuthStore()

async function submit() {
  err.value = ''
  loading.value = true
  try {
    const data = await api<any>('/auth/login', {
      method: 'POST',
      body: form.value,
    })
    auth.setTokens(data)
    navigateTo('/')
  } catch (e: any) {
    err.value = e?.data?.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="wrap">
    <h1>登录</h1>
    <form @submit.prevent="submit">
      <label>邮箱</label>
      <input v-model="form.email" type="email" autocomplete="email" required>
      <label>密码</label>
      <input v-model="form.password" type="password" autocomplete="current-password" required>
      <button :disabled="loading" type="submit">
        {{ loading ? '登录中...' : '登录' }}
      </button>
      <p v-if="err" class="err">{{ err }}</p>
    </form>
    <p class="tip">还没账号？<NuxtLink to="/register">注册</NuxtLink></p>
  </div>
</template>

<style scoped>
.wrap { max-width: 400px; margin: 40px auto; }
label { display: block; margin-top: 12px; font-weight: 500; }
input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  box-sizing: border-box;
}
button {
  margin-top: 16px;
  padding: 10px 20px;
  background: var(--link);
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  width: 100%;
}
.err { color: var(--lg-red); margin-top: 10px; }
.tip { margin-top: 12px; color: var(--text-muted); }
</style>
