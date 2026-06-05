<script setup lang="ts">
type CaptchaProvider = 'turnstile' | 'hcaptcha' | 'aliyun' | 'none'

declare global {
  interface Window {
    turnstile?: any
    hcaptcha?: any
    AliyunCaptchaConfig?: { region: string; prefix: string }
    initAliyunCaptcha?: (options: Record<string, any>) => void
  }
}

const props = withDefaults(defineProps<{
  idSuffix?: string
}>(), {
  idSuffix: 'default',
})

const emit = defineEmits<{
  verified: [token: string]
}>()

const config = useRuntimeConfig()
const provider = computed(() => (config.public.captchaProvider || 'none') as CaptchaProvider)
const token = ref('')
const ready = ref(false)
const error = ref('')
const widgetId = ref<any>(null)
const aliyunInited = ref(false)
const pendingResolve = ref<((token: string) => void) | null>(null)
const pendingReject = ref<((err: Error) => void) | null>(null)

const safeSuffix = computed(() => props.idSuffix.replace(/[^A-Za-z0-9_-]/g, '-'))
const elementId = computed(() => `captcha-element-${safeSuffix.value}`)
const buttonId = computed(() => `captcha-button-${safeSuffix.value}`)

function loadScript(src: string, id: string, beforeLoad?: () => void): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!import.meta.client) return resolve()
    const old = document.getElementById(id) as HTMLScriptElement | null
    if (old) {
      if ((old as any).dataset.loaded === '1') resolve()
      else old.addEventListener('load', () => resolve(), { once: true })
      return
    }
    beforeLoad?.()
    const script = document.createElement('script')
    script.id = id
    script.src = src
    script.async = true
    script.defer = true
    script.onload = () => {
      script.dataset.loaded = '1'
      resolve()
    }
    script.onerror = () => reject(new Error('验证码脚本加载失败'))
    document.head.appendChild(script)
  })
}

function resolveToken(value: string) {
  if (!value) return
  token.value = value
  emit('verified', value)
  pendingResolve.value?.(value)
  pendingResolve.value = null
  pendingReject.value = null
}

function waitForToken(): Promise<string> {
  if (token.value) return Promise.resolve(token.value)
  return new Promise((resolve, reject) => {
    pendingResolve.value = resolve
    pendingReject.value = reject
    window.setTimeout(() => {
      if (!token.value && pendingReject.value === reject) {
        pendingReject.value = null
        pendingResolve.value = null
        reject(new Error('人机验证超时，请重试'))
      }
    }, 120_000)
  })
}

function reset() {
  token.value = ''
  const p = provider.value
  if (p === 'turnstile' && window.turnstile && widgetId.value !== null) {
    window.turnstile.reset(widgetId.value)
  }
  if (p === 'hcaptcha' && window.hcaptcha && widgetId.value !== null) {
    window.hcaptcha.reset(widgetId.value)
  }
}

async function initTurnstile() {
  if (!config.public.captchaSiteKey) {
    error.value = '人机验证未配置 site key'
    return
  }
  await loadScript('https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit', 'cf-turnstile-api')
  widgetId.value = window.turnstile.render(`#${elementId.value}`, {
    sitekey: config.public.captchaSiteKey,
    callback: resolveToken,
    'expired-callback': reset,
    theme: 'auto',
  })
  ready.value = true
}

async function initHcaptcha() {
  if (!config.public.captchaSiteKey) {
    error.value = '人机验证未配置 site key'
    return
  }
  await loadScript('https://js.hcaptcha.com/1/api.js?render=explicit', 'hcaptcha-api')
  widgetId.value = window.hcaptcha.render(elementId.value, {
    sitekey: config.public.captchaSiteKey,
    callback: resolveToken,
    'expired-callback': reset,
  })
  ready.value = true
}

function pickAliyunToken(payload: any): string {
  if (!payload) return ''
  if (typeof payload === 'string') return payload
  return payload.captchaVerifyParam || payload.CaptchaVerifyParam || payload.captcha_verify_param || ''
}

async function initAliyun() {
  const prefix = String(config.public.captchaAliyunPrefix || '')
  const sceneId = String(config.public.captchaAliyunSceneId || '')
  const region = String(config.public.captchaAliyunRegion || 'cn')
  if (!prefix || !sceneId) {
    error.value = '阿里云验证码未配置 prefix 或 sceneId'
    return
  }
  await loadScript(
    'https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js',
    'aliyun-captcha-api',
    () => {
      window.AliyunCaptchaConfig = { region, prefix }
    },
  )
  window.initAliyunCaptcha?.({
    SceneId: sceneId,
    prefix,
    region,
    mode: 'popup',
    element: `#${elementId.value}`,
    button: `#${buttonId.value}`,
    language: 'cn',
    captchaVerifyCallback: (captchaVerifyParam: string) => {
      resolveToken(captchaVerifyParam)
      return { captchaResult: true, bizResult: true }
    },
    onBizResultCallback: () => {},
    success: (payload: any) => {
      resolveToken(pickAliyunToken(payload))
    },
    fail: () => {
      error.value = '人机验证失败，请重试'
    },
    onError: () => {
      error.value = '人机验证加载失败'
    },
  })
  aliyunInited.value = true
  ready.value = true
}

async function init() {
  if (!import.meta.client || provider.value === 'none') {
    ready.value = true
    return
  }
  try {
    if (provider.value === 'turnstile') await initTurnstile()
    else if (provider.value === 'hcaptcha') await initHcaptcha()
    else if (provider.value === 'aliyun') await initAliyun()
  } catch (e: any) {
    error.value = e?.message || '人机验证初始化失败'
  }
}

async function getToken(): Promise<string> {
  if (provider.value === 'none') return ''
  if (token.value) return token.value
  if (!ready.value) await init()

  if (provider.value === 'aliyun') {
    if (!aliyunInited.value) throw new Error(error.value || '阿里云验证码未初始化')
    document.getElementById(buttonId.value)?.click()
    return await waitForToken()
  }

  let executed = false
  if (provider.value === 'turnstile' && window.turnstile && widgetId.value !== null && window.turnstile.execute) {
    window.turnstile.execute?.(widgetId.value)
    executed = true
  }
  if (provider.value === 'hcaptcha' && window.hcaptcha && widgetId.value !== null && window.hcaptcha.execute) {
    window.hcaptcha.execute?.(widgetId.value)
    executed = true
  }
  if (executed) {
    return await waitForToken()
  }
  throw new Error('请先完成人机验证')
}

onMounted(init)

defineExpose({ getToken, reset })
</script>

<template>
  <div v-if="provider !== 'none'" class="captcha-wrap">
    <div :id="elementId" class="captcha-element" />
    <button
      v-if="provider === 'aliyun'"
      :id="buttonId"
      type="button"
      class="captcha-hidden-btn"
      tabindex="-1"
      aria-hidden="true"
    />
    <p v-if="error" class="captcha-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.captcha-wrap {
  margin-top: 12px;
  min-width: 0;
}

.captcha-element {
  min-height: 1px;
}

.captcha-hidden-btn {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  border: 0;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
}

.captcha-error {
  margin: 8px 0 0;
  color: var(--lg-red);
  font-size: 13px;
}
</style>
