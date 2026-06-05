<script setup lang="ts">
const form = ref({ email: '', password: '', display_name: '' })
const passwordConfirm = ref('')
const state = ref<'idle' | 'loading' | 'done'>('idle')
const err = ref('')
const captchaRef = ref<any>(null)

const api = useApi()

async function submit() {
  err.value = ''
  if (form.value.password !== passwordConfirm.value) {
    err.value = '两次输入的密码不一致'
    return
  }
  state.value = 'loading'
  try {
    const captchaToken = await captchaRef.value?.getToken?.()
    await api('/auth/register', {
      method: 'POST',
      body: {
        ...form.value,
        captcha_token: captchaToken || undefined,
      },
    })
    state.value = 'done'
  } catch (e: any) {
    err.value = e?.data?.message || '注册失败'
    captchaRef.value?.reset?.()
    state.value = 'idle'
  }
}
</script>

<template>
  <div class="wrap">
    <h1>注册</h1>
    <form v-if="state !== 'done'" @submit.prevent="submit">
      <label>邮箱</label>
      <input v-model="form.email" type="email" autocomplete="email" required>
      <label>显示名（1-16 字）</label>
      <input v-model="form.display_name" type="text" minlength="1" maxlength="16" required>
      <label>密码（至少 8 位，含字母和数字）</label>
      <input v-model="form.password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required>
      <label>确认密码</label>
      <input v-model="passwordConfirm" type="password" autocomplete="new-password" minlength="8" maxlength="128" required>
      <CaptchaChallenge ref="captchaRef" id-suffix="register" />
      <button :disabled="state === 'loading'" type="submit">
        {{ state === 'loading' ? '提交中...' : '注册' }}
      </button>
      <p v-if="err" class="err">{{ err }}</p>
    </form>
    <div v-else class="success">
      <h2>✓ 已发送验证邮件</h2>
      <p>请到 {{ form.email }} 的邮箱查收，24 小时内点击验证链接即可登录。</p>
    </div>
    <p class="tip">已有账号？<NuxtLink to="/login">登录</NuxtLink></p>
  </div>
</template>

<style scoped>
.wrap { max-width: 420px; margin: 40px auto; }
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
.success {
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--lg-green);
  border-radius: 6px;
}
.success h2 { color: var(--lg-green); margin-top: 0; }
.err { color: var(--lg-red); margin-top: 10px; }
.tip { margin-top: 12px; color: var(--text-muted); }
</style>
