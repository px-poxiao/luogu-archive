<script setup lang="ts">
const auth = useAuthStore()
const api = useApi()

const follows = ref<Array<{ uid: number; created_at: string }>>([])
interface MeData {
  email: string
  display_name: string
  follow_count: number
  luogu_uid: number | null
  luogu_bound_at: string | null
}

const me = ref<MeData | null>(null)
const loading = ref(true)

// 2FA state
const totpSetupUri = ref<string | null>(null)
const totpSetupShow = ref(false)
const totpConfirmCode = ref('')
const totpActionLoading = ref(false)

function handleBound(uid: number) {
  if (me.value) me.value.luogu_uid = uid
}

onMounted(async () => {
  if (!auth.isLoggedIn) {
    navigateTo('/login')
    return
  }
  try {
    const [followRows, meData] = await Promise.all([
      api<Array<{ uid: number; created_at: string }>>('/follows'),
      api<MeData>('/auth/me'),
    ])
    follows.value = followRows
    me.value = meData
  } catch (e: any) {
    console.error(e)
  } finally {
    loading.value = false
  }
})

async function enable2fa() {
  if (!me.value) return
  totpActionLoading.value = true
  try {
    const data = await api<{ provisioning_uri: string }>('/auth/2fa/setup', { method: 'POST' })
    totpSetupUri.value = data.provisioning_uri
    totpSetupShow.value = true
  } catch (e: any) {
    alert(e?.data?.message || '启用 2FA 失败')
  } finally {
    totpActionLoading.value = false
  }
}

async function confirmEnable() {
  if (!me.value) return
  if (!totpConfirmCode.value) {
    alert('请输入验证码')
    return
  }
  totpActionLoading.value = true
  try {
    await api('/auth/2fa/confirm', { method: 'POST', body: { code: totpConfirmCode.value } })
    alert('已启用 2FA')
    // refresh profile
    me.value = await api<MeData>('/auth/me')
    totpSetupShow.value = false
    totpSetupUri.value = null
    totpConfirmCode.value = ''
  } catch (e: any) {
    alert(e?.data?.message || '确认失败')
  } finally {
    totpActionLoading.value = false
  }
}

async function disable2fa() {
  if (!me.value) return
  const password = window.prompt('请输入登录密码以确认禁用 2FA')
  if (!password) return
  const code = window.prompt('请输入当前 2FA 验证码')
  if (!code) return
  totpActionLoading.value = true
  try {
    await api('/auth/2fa/disable', { method: 'POST', body: { password, totp_code: code } })
    alert('已禁用 2FA')
    me.value = await api<MeData>('/auth/me')
  } catch (e: any) {
    alert(e?.data?.message || '禁用失败')
  } finally {
    totpActionLoading.value = false
  }
}

</script>

<template>
  <div>
    <PageHero title="我的关注" />
    <section v-if="auth.isLoggedIn" class="account-bar">
      <div>
        <strong>{{ me?.display_name || auth.displayName }}</strong>
        <p>登录邮箱：{{ me?.email || auth.email }} · 已关注 {{ follows.length }} / 100</p>
      </div>
      <LuoguBindButton
        v-if="me"
        :luogu-uid="me?.luogu_uid ?? null"
        @bound="handleBound"
      />
        <div v-if="me" style="margin-left: 20px; text-align: right">
          <div style="font-size:13px; color:var(--text-muted)">
            2FA：<strong>{{ me?.totp_enabled ? '已启用' : '未启用' }}</strong>
          </div>
          <div style="margin-top:8px">
            <button v-if="!me?.totp_enabled" @click="enable2fa" :disabled="totpActionLoading">启用 2FA</button>
            <button v-else @click="disable2fa" :disabled="totpActionLoading">禁用 2FA</button>
          </div>
        </div>
    </section>

  <div v-if="totpSetupShow" class="totp-setup">
    <h3>启用 2FA</h3>
    <p>请使用 Google Authenticator / Authy 扫描下方二维码，或手动输入密钥。</p>
    <div v-if="totpSetupUri">
      <img :src="`https://chart.googleapis.com/chart?chs=200x200&chld=M|0&cht=qr&chl=${encodeURIComponent(totpSetupUri)}`" alt="QR">
    </div>
    <label>输入首次生成的 6 位验证码以确认启用</label>
    <input v-model="totpConfirmCode" maxlength="6" minlength="6" inputmode="numeric">
    <div>
      <button @click="confirmEnable" :disabled="totpActionLoading">确认启用</button>
      <button @click="() => { totpSetupShow = false; totpSetupUri = null; totpConfirmCode = '' }">取消</button>
    </div>
  </div>


    <div v-if="loading" class="loading">加载中...</div>
    <ul v-else-if="follows.length" class="list">
      <li v-for="f in follows" :key="f.uid">
        <NuxtLink :to="`/user/${f.uid}`">UID {{ f.uid }}</NuxtLink>
        <span class="time">关注于 {{ f.created_at }}</span>
      </li>
    </ul>
    <p v-else class="muted">还没关注任何洛谷用户。到用户主页点「关注」开始吧。</p>
  </div>
</template>

<style scoped>
.muted { color: var(--text-muted); }
.account-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 20px;
  padding: 15px 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}
.account-bar strong { font-size: 16px; }
.account-bar p { margin: 2px 0 0; color: var(--text-muted); font-size: 14px; }
.loading { padding: 20px; color: var(--text-muted); }
.list {
  list-style: none;
  padding: 0;
}
.list li {
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
}
.time { color: var(--text-muted); font-size: 13px; }
@media (max-width: 620px) {
  .account-bar { align-items: flex-start; flex-direction: column; }
}
</style>
