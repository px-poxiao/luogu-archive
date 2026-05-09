<script setup lang="ts">
const api = useApi()

const form = ref({
  requester_name: '',
  requester_contact: '',
  target_type: 'article',
  target_id: '',
  reason: '',
})

const state = ref<'idle' | 'submitting' | 'success' | 'failed'>('idle')
const message = ref('')

async function submit() {
  if (!form.value.target_id.trim() || !form.value.reason.trim()) {
    message.value = '请填写目标和原因'
    return
  }
  state.value = 'submitting'
  try {
    await api('/takedown', {
      method: 'POST',
      body: form.value,
    })
    state.value = 'success'
    message.value = '已提交，管理员会在 24h 内处理。感谢配合。'
  } catch (e: any) {
    state.value = 'failed'
    message.value = e?.data?.message || '提交失败'
  }
}
</script>

<template>
  <div class="wrap">
    <h1>侵权投诉 / 内容删除申请</h1>
    <p>
      本站为洛谷社区内容的第三方存档。如果你是原作者，或发现本站收录了侵犯你权益的内容，
      可以通过此表单申请删除，我们会在 24 小时内处理。
    </p>

    <form v-if="state !== 'success'" @submit.prevent="submit">
      <label>
        <span>你的称呼（选填）</span>
        <input v-model="form.requester_name" type="text" maxlength="128">
      </label>
      <label>
        <span>联系方式（选填，便于我们回复）</span>
        <input v-model="form.requester_contact" type="text" maxlength="256"
               placeholder="邮箱 / 其他">
      </label>
      <label>
        <span>内容类型</span>
        <select v-model="form.target_type">
          <option value="article">文章</option>
          <option value="paste">剪贴板</option>
          <option value="feed">犇犇</option>
          <option value="user">用户资料</option>
          <option value="judgement">陶片放逐</option>
          <option value="image">镜像图片</option>
        </select>
      </label>
      <label>
        <span>目标 ID</span>
        <input v-model="form.target_id" type="text" maxlength="64"
               placeholder="文章 ID / 剪贴板 ID / 用户 UID 等">
      </label>
      <label>
        <span>理由（必填）</span>
        <textarea v-model="form.reason" rows="6"
                  placeholder="请说明你与原内容的关系、希望如何处理等" />
      </label>

      <button type="submit" :disabled="state === 'submitting'">
        {{ state === 'submitting' ? '提交中...' : '提交申请' }}
      </button>
      <p v-if="message" :class="{ err: state === 'failed' }">{{ message }}</p>
    </form>

    <div v-else class="success">
      <h2>✓ 申请已提交</h2>
      <p>{{ message }}</p>
    </div>
  </div>
</template>

<style scoped>
.wrap { max-width: 720px; margin: 0 auto; }
label {
  display: block;
  margin: 16px 0;
}
label span {
  display: block;
  font-weight: 500;
  margin-bottom: 6px;
}
input, select, textarea {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  box-sizing: border-box;
}
button[type="submit"] {
  padding: 10px 24px;
  background: var(--link);
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 16px;
}
button[type="submit"]:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.err { color: var(--lg-red); }
.success {
  padding: 40px;
  background: var(--surface);
  border: 1px solid var(--lg-green);
  border-radius: 8px;
  text-align: center;
}
.success h2 { color: var(--lg-green); }
</style>
