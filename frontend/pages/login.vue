<script setup lang="ts">
const form = ref({ email: '', password: '' })
const err = ref('')
const loading = ref(false)

// 邮箱未验证时出现"重发验证邮件"入口
const needVerify = ref(false)
const resendMsg = ref('')
const resendCooldown = ref(0)
let cooldownTimer: ReturnType<typeof setInterval> | null = null

const api = useApi()
const auth = useAuthStore()

async function submit() {
  err.value = ''
  needVerify.value = false
  resendMsg.value = ''
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
    // 后端对未验证邮箱返回"请先验证邮箱"
    if (typeof err.value === 'string' && err.value.includes('验证邮箱')) {
      needVerify.value = true
    }
  } finally {
    loading.value = false
  }
}

function startCooldown(sec: number) {
  resendCooldown.value = sec
  if (cooldownTimer) clearInterval(cooldownTimer)
  cooldownTimer = setInterval(() => {
    resendCooldown.value -= 1
    if (resendCooldown.value <= 0 && cooldownTimer) {
      clearInterval(cooldownTimer)
      cooldownTimer = null
    }
  }, 1000)
}

async function resend() {
  if (resendCooldown.value > 0) return
  if (!form.value.email) {
    resendMsg.value = '请先填写邮箱'
    return
  }
  resendMsg.value = ''
  try {
    const data = await api<{ message: string }>('/auth/resend-verification', {
      method: 'POST',
      body: { email: form.value.email },
    })
    resendMsg.value = data.message || '已重新发送，请查收'
    startCooldown(60)
  } catch (e: any) {
    const retry = e?.data?.data?.retry_after_sec
    resendMsg.value = e?.data?.message || '发送失败'
    if (typeof retry === 'number' && retry > 0) startCooldown(retry)
  }
}

onUnmounted(() => {
  if (cooldownTimer) clearInterval(cooldownTimer)
})
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

    <div v-if="needVerify" class="resend-box">
      <p>邮箱还没验证？</p>
      <button class="resend-btn" :disabled="resendCooldown > 0" @click="resend">
        {{ resendCooldown > 0 ? `重新发送（${resendCooldown}s）` : '重新发送验证邮件' }}
      </button>
      <p v-if="resendMsg" class="resend-msg">{{ resendMsg }}</p>
    </div>

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

.resend-box {
  margin-top: 16px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
}
.resend-box > p { margin: 0 0 8px; color: var(--text-muted); font-size: 14px; }
.resend-btn {
  margin-top: 0;
  background: transparent;
  color: var(--link);
  border: 1px solid var(--link);
}
.resend-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.resend-msg { margin: 10px 0 0; font-size: 13px; color: var(--text-muted); }
</style>
