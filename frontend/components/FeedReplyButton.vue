<script setup lang="ts">
// 犇犇“回复”按钮：点一下把 ` || @[发送者] : 原内容` 复制到剪贴板。
const props = defineProps<{
  content: string
  senderName: string | null | undefined
}>()

const { copyReply } = useFeedReply()
const state = ref<'idle' | 'ok' | 'err'>('idle')
let timer: ReturnType<typeof setTimeout> | null = null

async function onClick() {
  const ok = await copyReply(props.content, props.senderName || '')
  state.value = ok ? 'ok' : 'err'
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { state.value = 'idle' }, 1500)
}

onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<template>
  <button
    type="button"
    class="reply-btn"
    :class="state"
    title="复制为洛谷回复格式"
    @click="onClick"
  >
    <svg viewBox="0 0 24 24" class="ic" aria-hidden="true">
      <path
        d="M10 9V5l-7 7 7 7v-4c5 0 8 1.5 10 5 0-7-3-11-10-11z"
        fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round"
      />
    </svg>
    <span>{{ state === 'ok' ? '已复制' : state === 'err' ? '失败' : '回复' }}</span>
  </button>
</template>

<style scoped>
.reply-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 5px;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s, background 0.12s;
}
.reply-btn:hover {
  color: var(--link);
  border-color: var(--link);
}
.reply-btn.ok {
  color: var(--lg-green);
  border-color: var(--lg-green);
}
.reply-btn.err {
  color: var(--lg-red);
  border-color: var(--lg-red);
}
.ic {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}
</style>
