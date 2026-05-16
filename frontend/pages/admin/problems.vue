<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const admin = useAdminStore()
const api = useAdminApi()

const form = reactive({
  p_min: 1000,
  p_max: 16501,
  b_min: 2001,
  b_max: 4528,
  delay_ms: 3000,
})

const state = ref<'idle' | 'pending' | 'done' | 'error'>('idle')
const message = ref('')

const totalCount = computed(() => {
  const p = Math.max(0, form.p_max - form.p_min + 1)
  const b = Math.max(0, form.b_max - form.b_min + 1)
  return p + b
})

const etaText = computed(() => {
  const sec = Math.round((totalCount.value * form.delay_ms) / 1000)
  if (sec < 60) return `${sec} 秒`
  if (sec < 3600) return `${Math.round(sec / 60)} 分钟`
  return `${(sec / 3600).toFixed(1)} 小时`
})

async function submit() {
  if (state.value === 'pending') return
  if (!confirm(`将派发 ${totalCount.value} 个任务，预计 ${etaText.value}。继续？`)) return
  state.value = 'pending'
  message.value = '派发中...'
  try {
    const resp = await api<{ message: string; count: number; eta_sec: number }>(
      '/admin/problems/full-refresh',
      { method: 'POST', body: form },
    )
    state.value = 'done'
    message.value = `已派发 ${resp.count} 条任务，预计 ${Math.round(resp.eta_sec / 60)} 分钟完成`
  } catch (e: any) {
    state.value = 'error'
    message.value = e?.data?.message || '失败'
  }
}

onMounted(() => {
  if (!admin.isLoggedIn) navigateTo('/admin/login')
})
</script>

<template>
  <div>
    <h1>题库全量刷新</h1>
    <p class="note">
      洛谷"不允许提交题解"通常是终态，定时巡检不会重扫。<br>
      使用此功能可以强制重新检测整个题库的题解开放状态，覆盖关闭后被重新开放的题，并发现新增题号。
    </p>

    <section class="form">
      <div class="row">
        <label>P 题号范围</label>
        <input v-model.number="form.p_min" type="number" min="1">
        <span>~</span>
        <input v-model.number="form.p_max" type="number" min="1">
      </div>
      <div class="row">
        <label>B 题号范围</label>
        <input v-model.number="form.b_min" type="number" min="1">
        <span>~</span>
        <input v-model.number="form.b_max" type="number" min="1">
      </div>
      <div class="row">
        <label>任务间隔 (ms)</label>
        <input v-model.number="form.delay_ms" type="number" min="500" max="30000">
        <span class="muted">越小越快，但可能触发洛谷限流</span>
      </div>

      <div class="summary">
        <div>总任务数：<b>{{ totalCount }}</b></div>
        <div>预计耗时：<b>{{ etaText }}</b></div>
      </div>

      <button :disabled="state === 'pending' || totalCount === 0" @click="submit">
        {{ state === 'pending' ? '派发中…' : '开始全量刷新' }}
      </button>
      <p v-if="message" :class="['msg', state]">{{ message }}</p>
    </section>

    <section class="warn">
      <h3>注意事项</h3>
      <ul>
        <li>断号在范围内表现为 404，任务自身会处理（不熔断、不重试）</li>
        <li>建议间隔 ≥ 3 秒，避免节点被洛谷拦截 5 分钟</li>
        <li>派发后任务会按错峰队列依次执行，无需关闭页面</li>
        <li>可以从前台 <code>/problem/list</code> 看到结果逐步出现</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.note {
  color: var(--text-muted);
  margin-bottom: 24px;
  line-height: 1.7;
}
.form {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 18px 22px;
  max-width: 720px;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.row label {
  width: 130px;
  color: var(--text-muted);
}
.row input {
  width: 100px;
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--text);
}
.row .muted {
  color: var(--text-muted);
  font-size: 13px;
}
.summary {
  margin: 16px 0;
  padding: 12px 14px;
  background: var(--bg);
  border-radius: 6px;
  display: flex;
  gap: 30px;
  font-size: 14px;
}
button {
  padding: 8px 22px;
  background: var(--link);
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}
button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.msg {
  margin-top: 10px;
  font-size: 14px;
}
.msg.done { color: var(--lg-green); }
.msg.error { color: var(--lg-red); }
.msg.pending { color: var(--lg-orange); }

.warn {
  margin-top: 24px;
  background: var(--banner-bg);
  border: 1px solid var(--banner-border);
  border-radius: 6px;
  padding: 12px 18px;
  max-width: 720px;
}
.warn h3 { margin-top: 0; font-size: 15px; }
.warn ul { margin: 8px 0; padding-left: 20px; line-height: 1.8; font-size: 14px; }
.warn code {
  background: var(--hover);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 13px;
}
</style>
