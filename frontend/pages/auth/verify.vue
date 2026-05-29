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
  <div class="verify-page">
    <div class="card" :class="state">
      <!-- 状态图标 -->
      <div class="icon-wrap">
        <!-- loading：旋转圈 -->
        <div v-if="state === 'loading'" class="spinner" aria-label="验证中"></div>

        <!-- success：对勾，带描边动画 -->
        <svg v-else-if="state === 'success'" class="status-svg" viewBox="0 0 52 52">
          <circle class="circle ok" cx="26" cy="26" r="24" fill="none" />
          <path class="check" fill="none" d="M14 27l8 8 16-16" />
        </svg>

        <!-- error：叉，带描边动画 -->
        <svg v-else class="status-svg" viewBox="0 0 52 52">
          <circle class="circle bad" cx="26" cy="26" r="24" fill="none" />
          <path class="cross" fill="none" d="M18 18l16 16M34 18L18 34" />
        </svg>
      </div>

      <h1 class="title">
        <template v-if="state === 'loading'">正在验证邮箱</template>
        <template v-else-if="state === 'success'">验证成功</template>
        <template v-else>验证未成功</template>
      </h1>

      <p class="desc">
        <template v-if="state === 'loading'">请稍候，正在确认你的验证链接…</template>
        <template v-else>{{ message }}</template>
      </p>

      <div class="actions">
        <NuxtLink v-if="state === 'success'" to="/login" class="btn primary">
          前往登录
        </NuxtLink>
        <template v-else-if="state === 'error'">
          <NuxtLink to="/login" class="btn ghost">去登录页重发</NuxtLink>
          <NuxtLink to="/register" class="btn primary">重新注册</NuxtLink>
        </template>
      </div>

      <NuxtLink to="/" class="home-link">返回首页</NuxtLink>
    </div>
  </div>
</template>

<style scoped>
.verify-page {
  min-height: 70vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 16px;
}

.card {
  width: 100%;
  max-width: 420px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 40px 32px 28px;
  text-align: center;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.06);
  animation: card-in 0.4s cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes card-in {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 顶部色条随状态变化 */
.card { position: relative; overflow: hidden; }
.card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 4px;
  background: var(--link);
}
.card.success::before { background: var(--lg-green); }
.card.error::before { background: var(--lg-red); }

.icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 84px;
  margin-bottom: 18px;
}

/* loading 旋转圈 */
.spinner {
  width: 52px;
  height: 52px;
  border: 4px solid var(--border);
  border-top-color: var(--link);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* success / error SVG */
.status-svg {
  width: 84px;
  height: 84px;
}
.circle {
  stroke-width: 3;
  stroke-dasharray: 151;
  stroke-dashoffset: 151;
  animation: draw-circle 0.5s ease forwards;
}
.circle.ok { stroke: var(--lg-green); }
.circle.bad { stroke: var(--lg-red); }
.check, .cross {
  stroke-width: 4;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 60;
  stroke-dashoffset: 60;
  animation: draw-mark 0.4s 0.4s ease forwards;
}
.check { stroke: var(--lg-green); }
.cross { stroke: var(--lg-red); }
@keyframes draw-circle { to { stroke-dashoffset: 0; } }
@keyframes draw-mark { to { stroke-dashoffset: 0; } }

.title {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 700;
}
.desc {
  margin: 0 0 24px;
  color: var(--text-muted);
  font-size: 15px;
  line-height: 1.6;
}

.actions {
  display: flex;
  gap: 10px;
  justify-content: center;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.btn {
  display: inline-block;
  padding: 10px 22px;
  border-radius: 8px;
  font-size: 15px;
  text-decoration: none;
  transition: transform 0.12s, box-shadow 0.12s, background 0.12s;
}
.btn:hover { text-decoration: none; transform: translateY(-1px); }
.btn.primary {
  background: var(--link);
  color: #fff;
  box-shadow: 0 4px 12px rgba(9, 105, 218, 0.25);
}
.btn.primary:hover { box-shadow: 0 6px 16px rgba(9, 105, 218, 0.35); }
.btn.ghost {
  background: transparent;
  color: var(--text);
  border: 1px solid var(--border);
}
.btn.ghost:hover { background: var(--hover); }

.home-link {
  display: inline-block;
  color: var(--text-muted);
  font-size: 13px;
}
.home-link:hover { color: var(--link); }
</style>
