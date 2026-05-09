<!--
  原文归属横幅 + 保存按钮。
  所有内容详情页（文章/剪贴板/用户/陶片等）顶部挂一个。
-->
<script setup lang="ts">
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const props = defineProps<{
  originUrl: string           // 对应洛谷原站 URL
  authorName?: string
  authorHref?: string
  crawledAt?: string | Date
  // 保存按钮参数
  contentType: string
  contentId: string
}>()

const state = ref<'idle' | 'pending' | 'success' | 'failed' | 'cooldown' | 'captcha'>('idle')
const message = ref<string>('')
const captchaToken = ref<string>('')

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
    state.value = 'success'
    message.value = resp.merged ? '已合并到进行中的任务' : '已派发，请稍后刷新'
    setTimeout(() => {
      state.value = 'idle'
      message.value = ''
    }, 3000)
  } catch (e: any) {
    const code = e?.data?.error_code
    if (code === 'captcha_required') {
      state.value = 'captcha'
      message.value = '请先完成人机验证'
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

const relTime = computed(() =>
  props.crawledAt ? dayjs(props.crawledAt).fromNow() : '未知',
)
</script>

<template>
  <div class="origin-banner">
    <div style="flex: 1; min-width: 0;">
      本站为第三方存档 ·
      <a :href="originUrl" target="_blank" rel="noopener noreferrer">查看洛谷原文</a>
      <span v-if="authorName">
        · 作者：
        <a v-if="authorHref" :href="authorHref">{{ authorName }}</a>
        <span v-else>{{ authorName }}</span>
      </span>
      · 上次更新：{{ relTime }}
    </div>
    <button
      class="save-btn"
      :class="{
        success: state === 'success',
        error: state === 'failed',
        cooldown: state === 'cooldown' || state === 'captcha',
      }"
      :disabled="state === 'pending'"
      @click="save"
    >
      <span v-if="state === 'idle'">🔄 立即更新</span>
      <span v-else>{{ message }}</span>
    </button>
  </div>
</template>
