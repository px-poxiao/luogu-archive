<script setup lang="ts">
// 一键保存 / 更新按钮。封装 POST /save，并在需要时弹出人机验证。
const props = defineProps<{
  contentType: string
  contentId: string
}>()

const state = ref<'idle' | 'pending' | 'success' | 'failed' | 'cooldown' | 'captcha'>('idle')
const message = ref<string>('')
const captchaToken = ref<string>('')
const showCaptcha = ref(false)
const captchaRef = ref<any>(null)

const api = useApi()

async function save() {
  if (state.value === 'pending') return
  state.value = 'pending'
  message.value = '排队中...'
  try {
    const resp = await api<{ task_id: string; merged: boolean; status: string }>(
      '/save',
      {
        method: 'POST',
        body: {
          content_type: props.contentType,
          id: props.contentId,
          captcha_token: captchaToken.value || undefined,
        },
      },
    )
    showCaptcha.value = false
    captchaToken.value = ''
    captchaRef.value?.reset?.()
    state.value = 'success'
    message.value = resp.merged ? '已合并到进行中的任务' : '已派发，请稍后刷新'
    setTimeout(() => { state.value = 'idle'; message.value = '' }, 3000)
  } catch (e: any) {
    const code = e?.data?.error_code
    if (code === 'captcha_required') {
      state.value = 'captcha'
      showCaptcha.value = true
      message.value = '请完成人机验证'
      await nextTick()
      try {
        captchaToken.value = await captchaRef.value?.getToken?.()
        await save()
      } catch (err: any) {
        message.value = err?.message || '请先完成人机验证'
      }
    } else if (code === 'rate_limited') {
      state.value = 'cooldown'
      const s = e?.data?.data?.retry_after_sec || 30
      message.value = `冷却中 ${s}s`
      setTimeout(() => { state.value = 'idle' }, s * 1000)
    } else {
      state.value = 'failed'
      message.value = e?.data?.message || '失败'
      setTimeout(() => { state.value = 'idle' }, 3000)
    }
  }
}

async function onCaptchaVerified(token: string) {
  if (state.value !== 'captcha') return
  captchaToken.value = token
  await save()
}
</script>

<template>
  <div class="save-action">
    <button
      class="archive-action-button"
      :class="{
        success: state === 'success',
        error: state === 'failed',
        cooldown: state === 'cooldown' || state === 'captcha',
      }"
      :disabled="state === 'pending'"
      @click="save"
    >
      <span v-if="state === 'idle'">立即更新</span>
      <span v-else>{{ message }}</span>
    </button>
    <CaptchaChallenge
      v-if="showCaptcha"
      ref="captchaRef"
      :id-suffix="`save-${contentType}-${contentId}`"
      @verified="onCaptchaVerified"
    />
  </div>
</template>

<style scoped>
.save-action {
  display: grid;
  gap: 8px;
}

.archive-action-button.success { color: var(--lg-green); border-color: var(--lg-green); }
.archive-action-button.error { color: var(--lg-red); border-color: var(--lg-red); }
.archive-action-button.cooldown { color: var(--lg-orange); border-color: var(--lg-orange); }
</style>
