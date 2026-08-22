<script setup lang="ts">
const api = useApi()
const auth = useAuthStore()
const form = ref({ target_url: '', requester_name: '', requester_email: '', reason: '' })
const probe = ref<any>(null)
const probing = ref(false)
const state = ref<'idle' | 'submitting' | 'success' | 'failed'>('idle')
const message = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let probeVersion = 0

watch(
  [() => auth.initialized, () => auth.isLoggedIn, () => auth.email],
  () => {
    // 登录态异步恢复后自动带入注册邮箱，但不覆盖用户已经修改的内容。
    if (auth.initialized && auth.isLoggedIn && !form.value.requester_email) {
      form.value.requester_email = auth.email
    }
  },
  { immediate: true },
)

const typeNames: Record<string, string> = {
  user: '用户主页',
  article: '文章',
  paste: '剪贴板',
  feed: '犇犇',
}

async function runProbe() {
  const version = ++probeVersion
  const url = form.value.target_url.trim()
  probe.value = null
  message.value = ''
  if (!/^https?:\/\//i.test(url)) return
  probing.value = true
  try {
    const queued: any = await api('/takedown/probe', {
      method: 'POST',
      body: { target_url: url },
    })
    // 地址识别由后端立即完成，耗时的可访问性探测仍在高优先级队列中继续。
    probe.value = queued
    if (queued.status === 'completed') {
      return
    }
    for (let attempt = 0; attempt < 300 && version === probeVersion; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 2000))
      if (version !== probeVersion) return
      const current: any = await api(`/takedown/probe/${queued.token}`)
      if (current.status === 'completed') {
        probe.value = current
        return
      }
    }
    if (version === probeVersion) message.value = '地址检查超时，请稍后重试'
  } catch (e: any) {
    if (version === probeVersion) message.value = e?.data?.message || '地址检查失败'
  } finally {
    if (version === probeVersion) probing.value = false
  }
}

watch(() => form.value.target_url, () => {
  probeVersion += 1
  clearTimeout(timer)
  probe.value = null
  timer = setTimeout(runProbe, 600)
})

async function submit() {
  if (!probe.value?.can_submit) return
  if (!probe.value.is_owner && form.value.reason.trim().length < 10) {
    message.value = '请填写至少 10 个字的申请理由'
    return
  }
  state.value = 'submitting'
  try {
    const result: any = await api('/takedown', {
      method: 'POST',
      body: { probe_token: probe.value.token, requester_name: form.value.requester_name,
        requester_email: form.value.requester_email || null,
        reason: form.value.reason },
    })
    state.value = 'success'
    message.value = result.auto_approved ? '身份匹配，内容已停止公开展示。' : '申请已提交，等待管理员处理。'
  } catch (e: any) {
    state.value = 'failed'
    message.value = e?.data?.message || '提交失败'
  }
}
</script>

<template>
  <div class="wrap">
    <PageHero title="内容删除申请" subtitle="对已无法在原站访问的存档内容申请停止公开展示。" />
    <div v-if="state === 'success'" class="success"><h2>申请处理完成</h2><p>{{ message }}</p></div>
    <form v-else @submit.prevent="submit">
      <label class="address-field">
        <span>内容地址</span>
        <input v-model.trim="form.target_url" type="url"
          placeholder="粘贴用户主页、文章、剪贴板或犇犇的完整地址" maxlength="1024">
        <small>系统会自动识别内容类型</small>
        <span v-if="probe?.target_type && probe?.target_id" class="recognized">
          识别到：{{ typeNames[probe.target_type] || probe.target_type }}：{{ probe.target_id }}
        </span>
      </label>

      <div v-if="probing" class="probe neutral">loading……</div>
      <div v-else-if="probe && probe.target_type !== 'user'"
        class="probe" :class="probe.accessible ? 'blocked' : 'allowed'">
        <strong>{{ probe.accessible ? '可访问' : '不可访问' }}</strong>
        <span>{{ probe.accessible ? '原内容仍可访问，暂不能提交申请。' : '可以提交删除申请。' }}</span>
      </div>
      <div v-else-if="probe" class="probe allowed">
        <strong>地址有效</strong><span>用户主页申请无需检查原站访问状态。</span>
      </div>

      <template v-if="probe?.can_submit">
        <div v-if="probe.is_owner" class="owner-note">已匹配绑定的洛谷 UID，提交后将自动停止公开展示。</div>
        <template v-else>
          <div class="target-grid">
            <label><span>你的称呼（选填）</span><input v-model="form.requester_name" maxlength="128"></label>
            <label><span>联系邮箱（选填）</span><input
              v-model.trim="form.requester_email" type="email" autocomplete="email" maxlength="254"></label>
          </div>
          <label><span>申请理由</span><textarea v-model="form.reason" rows="6" maxlength="5000"
            placeholder="请说明内容关系及停止公开展示的理由" /></label>
        </template>
      </template>
      <p class="self-service-note">
        自己的内容？<NuxtLink to="/login">登录</NuxtLink>或<NuxtLink to="/register">注册</NuxtLink>并在<NuxtLink to="/me">个人中心绑定洛谷账号</NuxtLink>后，可无条件自动删除。
      </p>
      <button type="submit" :disabled="!probe?.can_submit || state === 'submitting'">
        {{ state === 'submitting' ? 'loading……' : '提交申请' }}
      </button>
      <p v-if="message" class="err">{{ message }}</p>
    </form>
  </div>
</template>

<style scoped>
.wrap{max-width:860px;margin:0 auto}form{padding:24px 0}.target-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.target-grid>label:only-child{grid-column:1/-1}
label{display:block;margin:14px 0}label span{display:block;font-weight:600;margin-bottom:7px}input,select,textarea{box-sizing:border-box;width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font:inherit}
.address-field{margin:8px 0 20px}.address-field input{min-height:58px;padding:14px 16px;font-size:17px}.address-field small{display:block;margin-top:7px;color:var(--text-muted)}
.address-field .recognized{display:block;margin-top:10px;color:var(--text);font-weight:600}
.probe,.owner-note{display:flex;align-items:center;gap:14px;margin:18px 0;padding:14px 16px;border:1px solid var(--border);border-radius:6px}.probe.allowed,.owner-note{border-color:var(--lg-green);background:color-mix(in srgb,var(--lg-green) 9%,var(--surface))}.probe.blocked{border-color:var(--lg-red);background:color-mix(in srgb,var(--lg-red) 8%,var(--surface))}.neutral{color:var(--text-muted)}
.self-service-note{margin:18px 0 10px;color:var(--text-muted);font-size:14px}
button{padding:10px 24px;border:0;border-radius:6px;background:var(--link);color:#fff;font:inherit;cursor:pointer}button:disabled{cursor:not-allowed;opacity:.5}.err{color:var(--lg-red)}.success{padding:36px;border:1px solid var(--lg-green);text-align:center}.success h2{color:var(--lg-green)}
@media(max-width:700px){.target-grid{grid-template-columns:1fr;gap:0}.probe{align-items:flex-start;flex-direction:column;gap:4px}}
</style>
