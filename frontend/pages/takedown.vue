<script setup lang="ts">
const api = useApi()
const form = ref({ target_type: 'article', target_url: '', requester_name: '', requester_contact: '', reason: '' })
const probe = ref<any>(null)
const probing = ref(false)
const state = ref<'idle' | 'submitting' | 'success' | 'failed'>('idle')
const message = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let probeVersion = 0

const placeholders: Record<string, string> = {
  article: 'https://www.luogu.com.cn/article/文章编号',
  paste: 'https://www.luogu.com.cn/paste/剪贴板编号',
  feed: 'https://www.luogu.com.cn/feed/犇犇编号',
  user: 'https://www.luogu.com.cn/user/用户UID',
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
      body: { target_type: form.value.target_type, target_url: url },
    })
    if (queued.status === 'completed') {
      probe.value = queued
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

watch(() => [form.value.target_type, form.value.target_url], () => {
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
        requester_contact: form.value.requester_contact, reason: form.value.reason },
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
      <div class="target-grid">
        <label><span>内容类型</span><select v-model="form.target_type">
          <option value="article">文章</option><option value="paste">剪贴板</option>
          <option value="feed">犇犇</option><option value="user">用户主页</option>
        </select></label>
        <label><span>对应地址</span><input v-model.trim="form.target_url" type="url"
          :placeholder="placeholders[form.target_type]" maxlength="1024"></label>
      </div>

      <div v-if="probing" class="probe neutral">loading……</div>
      <div v-else-if="probe && form.target_type !== 'user'"
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
            <label><span>联系方式（选填）</span><input v-model="form.requester_contact" maxlength="256"></label>
          </div>
          <label><span>申请理由</span><textarea v-model="form.reason" rows="6" maxlength="5000"
            placeholder="请说明内容关系及停止公开展示的理由" /></label>
        </template>
      </template>
      <button type="submit" :disabled="!probe?.can_submit || state === 'submitting'">
        {{ state === 'submitting' ? 'loading……' : '提交申请' }}
      </button>
      <p v-if="message" class="err">{{ message }}</p>
    </form>
  </div>
</template>

<style scoped>
.wrap{max-width:860px;margin:0 auto}form{padding:24px 0}.target-grid{display:grid;grid-template-columns:220px 1fr;gap:18px}
label{display:block;margin:14px 0}label span{display:block;font-weight:600;margin-bottom:7px}input,select,textarea{box-sizing:border-box;width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font:inherit}
.probe,.owner-note{display:flex;align-items:center;gap:14px;margin:18px 0;padding:14px 16px;border:1px solid var(--border);border-radius:6px}.probe.allowed,.owner-note{border-color:var(--lg-green);background:color-mix(in srgb,var(--lg-green) 9%,var(--surface))}.probe.blocked{border-color:var(--lg-red);background:color-mix(in srgb,var(--lg-red) 8%,var(--surface))}.neutral{color:var(--text-muted)}
button{padding:10px 24px;border:0;border-radius:6px;background:var(--link);color:#fff;font:inherit;cursor:pointer}button:disabled{cursor:not-allowed;opacity:.5}.err{color:var(--lg-red)}.success{padding:36px;border:1px solid var(--lg-green);text-align:center}.success h2{color:var(--lg-green)}
@media(max-width:700px){.target-grid{grid-template-columns:1fr;gap:0}.probe{align-items:flex-start;flex-direction:column;gap:4px}}
</style>
