<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const form = ref({ username: '', password: '', totp_code: '' })
const err = ref('')
const loading = ref(false)

const api = useAdminApi()
const admin = useAdminStore()

async function submit() {
  err.value = ''
  loading.value = true
  try {
    const data = await api<any>('/admin/login', { method: 'POST', body: form.value })
    admin.setToken(data)
    navigateTo('/admin')
  } catch (e: any) {
    err.value = e?.data?.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="wrap">
    <h1>管理员登录</h1>
    <form @submit.prevent="submit">
      <label>用户名</label>
      <input v-model="form.username" required>
      <label>密码</label>
      <input v-model="form.password" type="password" required>
      <label>2FA 验证码（6 位）</label>
      <input v-model="form.totp_code" maxlength="6" minlength="6" inputmode="numeric" required>
      <button :disabled="loading" type="submit">
        {{ loading ? '登录中...' : '登录' }}
      </button>
      <p v-if="err" class="err">{{ err }}</p>
    </form>
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
  box-sizing: border-box;
}
button {
  margin-top: 16px;
  width: 100%;
  padding: 10px;
  background: var(--link);
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.err { color: var(--lg-red); margin-top: 10px; }
</style>
