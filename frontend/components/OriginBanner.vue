<!--
  蓝色渐变页面头图 + 原文归属 + 保存按钮。
  内容详情页（文章/剪贴板/用户/陶片/题目）顶部挂一个。
-->
<script setup lang="ts">
const { fromNow } = useTime()

const props = defineProps<{
  originUrl: string           // 对应洛谷原站 URL
  title?: string              // 头图大标题（不传则不显示标题行）
  compact?: boolean           // 紧凑模式：不渲染蓝色大块，仅朴素归属+保存条
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
  props.crawledAt ? fromNow(props.crawledAt) : '未知',
)
</script>

<template>
  <div class="origin-hero" :class="{ compact }">
    <div class="hero-inner">
      <h1 v-if="title" class="hero-title">{{ title }}</h1>
      <div class="hero-meta">
        <span class="attr">
          <a :href="originUrl" target="_blank" rel="noopener noreferrer">查看洛谷原文</a>
          <span v-if="authorName">
            · 作者：
            <a v-if="authorHref" :href="authorHref">{{ authorName }}</a>
            <span v-else>{{ authorName }}</span>
          </span>
          · 上次更新：{{ relTime }}
        </span>
        <button
          class="hero-save-btn"
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
    </div>
  </div>
</template>

<style scoped>
.origin-hero {
  position: relative;
  border-radius: 12px;
  padding: 22px 26px;
  margin-bottom: 20px;
  overflow: hidden;
  background: var(--hero-bg);
  border: 1px solid var(--hero-border);
}
.hero-inner {
  position: relative;
  z-index: 1;
}
.hero-title {
  margin: 0 0 10px;
  color: var(--hero-text);
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 0.3px;
}
.hero-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.attr {
  flex: 1;
  min-width: 0;
  color: var(--hero-text-muted);
  font-size: 13.5px;
}
.attr a {
  color: var(--link);
  text-decoration: none;
}
.attr a:hover { text-decoration: underline; }

/* 保存按钮：白底，叠在浅蓝头图上 */
.hero-save-btn {
  flex-shrink: 0;
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid var(--hero-border);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font-size: 13.5px;
  transition: background 0.15s, border-color 0.15s, transform 0.1s, color 0.15s;
}
.hero-save-btn:hover:not(:disabled) {
  border-color: var(--link);
  color: var(--link);
  transform: translateY(-1px);
}
.hero-save-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.hero-save-btn.success { color: var(--lg-green); border-color: var(--lg-green); }
.hero-save-btn.error { color: var(--lg-red); border-color: var(--lg-red); }
.hero-save-btn.cooldown { color: var(--lg-orange); border-color: var(--lg-orange); }

@media (max-width: 768px) {
  .origin-hero { padding: 18px 16px; border-radius: 12px; }
  .hero-title { font-size: 21px; }
}

/* 紧凑模式：用于已有自己标题头的页面，仅朴素归属+保存条 */
.origin-hero.compact {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 16px;
}
.origin-hero.compact .hero-title { display: none; }
</style>
