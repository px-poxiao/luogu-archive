<script setup lang="ts">
const props = defineProps<{ luoguUid: number | null }>()
const emit = defineEmits<{ bound: [uid: number] }>()

const api = useApi()
const open = ref(false)
const loading = ref(false)
const verifying = ref(false)
const verificationText = ref('')
const pasteId = ref('')
const errorText = ref('')
const copied = ref(false)

async function begin() {
  if (props.luoguUid) return
  open.value = true
  errorText.value = ''
  if (verificationText.value) return
  loading.value = true
  try {
    const data = await api<{ verification_text: string }>('/auth/luogu-bind/challenge', {
      method: 'POST',
    })
    verificationText.value = data.verification_text
  } catch (error: any) {
    errorText.value = error?.data?.message || '生成验证文本失败'
  } finally {
    loading.value = false
  }
}

async function copyText() {
  if (!verificationText.value) return
  await navigator.clipboard.writeText(verificationText.value)
  copied.value = true
  window.setTimeout(() => { copied.value = false }, 1600)
}

async function verify() {
  if (!pasteId.value.trim()) {
    errorText.value = '请输入剪贴板 ID'
    return
  }
  verifying.value = true
  errorText.value = ''
  try {
    const data = await api<{ luogu_uid: number }>('/auth/luogu-bind/verify', {
      method: 'POST',
      body: { paste_id: pasteId.value.trim() },
    })
    emit('bound', data.luogu_uid)
    open.value = false
  } catch (error: any) {
    errorText.value = error?.data?.message || '验证失败，请检查剪贴板内容和公开状态'
  } finally {
    verifying.value = false
  }
}
</script>

<template>
  <NuxtLink v-if="luoguUid" :to="`/user/${luoguUid}`" class="bound-link">
    已绑定 UID {{ luoguUid }}
  </NuxtLink>
  <button v-else class="bind-trigger" type="button" @click="begin">绑定洛谷账号</button>

  <Teleport to="body">
    <div v-if="open" class="bind-backdrop" @click.self="open = false">
      <section class="bind-dialog" role="dialog" aria-modal="true" aria-labelledby="bind-title">
        <header class="dialog-head">
          <div>
            <h2 id="bind-title">绑定洛谷账号</h2>
          </div>
          <button class="close-btn" type="button" title="关闭" aria-label="关闭" @click="open = false">×</button>
        </header>

        <div v-if="loading" class="loading-line">正在生成验证文本...</div>
        <template v-else-if="verificationText">
          <label class="field-label" for="bind-text">1. 复制下面的完整文本</label>
          <div class="copy-box">
            <textarea id="bind-text" :value="verificationText" readonly rows="4" />
            <button type="button" class="copy-btn" @click="copyText">{{ copied ? '已复制' : '复制' }}</button>
          </div>

          <div class="step-row">
            <span>2. 用要绑定的账号新建公开剪贴板并粘贴文本</span>
            <a href="https://www.luogu.com.cn/paste" target="_blank" rel="noopener noreferrer">新建剪贴板</a>
          </div>

          <label class="field-label" for="paste-id">3. 输入剪贴板 ID</label>
          <input
            id="paste-id"
            v-model="pasteId"
            type="text"
            autocomplete="off"
            placeholder="剪贴板 ID、/paste/ID 或完整链接"
            @keyup.enter="verify"
          >
        </template>

        <p v-if="errorText" class="error-text">{{ errorText }}</p>
        <footer class="dialog-actions">
          <button class="cancel-btn" type="button" @click="open = false">取消</button>
          <button
            class="verify-btn"
            type="button"
            :disabled="loading || verifying || !verificationText"
            @click="verify"
          >{{ verifying ? '正在验证...' : '验证并绑定' }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.bind-trigger,
.bound-link {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid var(--link);
  border-radius: 6px;
  background: var(--link);
  color: #fff;
  font: inherit;
  font-size: 14px;
  cursor: pointer;
  text-decoration: none;
}
.bound-link { background: var(--surface); color: var(--link); }
.bind-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgb(0 0 0 / 48%);
}
.bind-dialog {
  width: min(520px, 100%);
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  box-sizing: border-box;
  padding: 22px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 18px 48px rgb(0 0 0 / 24%);
}
.dialog-head { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.dialog-head h2 { margin: 0; font-size: 20px; }
.dialog-head p { margin: 3px 0 0; color: var(--text-muted); font-size: 14px; }
.close-btn {
  width: 32px;
  height: 32px;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 25px;
  line-height: 1;
  cursor: pointer;
}
.field-label { display: block; margin: 14px 0 6px; font-size: 14px; font-weight: 600; }
.copy-box { position: relative; }
.copy-box textarea,
#paste-id {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text);
  font: inherit;
}
.copy-box textarea { resize: none; padding: 10px 72px 10px 12px; line-height: 1.55; }
#paste-id { height: 40px; padding: 0 11px; }
.copy-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
}
.step-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 16px; font-size: 14px; }
.step-row a { white-space: nowrap; }
.loading-line { padding: 18px 0; color: var(--text-muted); }
.error-text { margin: 12px 0 0; color: #cf222e; font-size: 14px; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
.cancel-btn,
.verify-btn { min-height: 38px; padding: 0 15px; border-radius: 6px; font: inherit; cursor: pointer; }
.cancel-btn { border: 1px solid var(--border); background: var(--surface); color: var(--text); }
.verify-btn { border: 1px solid var(--link); background: var(--link); color: #fff; }
.verify-btn:disabled { opacity: .55; cursor: not-allowed; }
@media (max-width: 520px) {
  .bind-dialog { padding: 18px; }
  .step-row { align-items: flex-start; flex-direction: column; gap: 6px; }
}
</style>
