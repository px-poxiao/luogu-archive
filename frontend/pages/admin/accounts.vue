<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const admin = useAdminStore()
const api = useAdminApi()

const accounts = ref<any[]>([])
const form = ref({ label: '', luogu_uid: 0, uid_value: '', client_id: '', c3vk: '' })
const adding = ref(false)

async function load() {
  accounts.value = await api('/admin/crawler-accounts')
}

onMounted(() => {
  if (!admin.isLoggedIn) {
    navigateTo('/admin/login')
    return
  }
  load()
})

async function add() {
  if (!form.value.label || !form.value.luogu_uid || !form.value.uid_value || !form.value.client_id) {
    alert('请填写 label / luogu_uid / _uid / __client_id')
    return
  }
  adding.value = true
  try {
    await api('/admin/crawler-accounts', { method: 'POST', body: form.value })
    form.value = { label: '', luogu_uid: 0, uid_value: '', client_id: '', c3vk: '' }
    await load()
  } catch (e: any) {
    alert(e?.data?.message || '失败')
  } finally {
    adding.value = false
  }
}

async function toggle(a: any) {
  const action = a.enabled ? 'disable' : 'enable'
  await api(`/admin/crawler-accounts/${a.id}/${action}`, { method: 'POST' })
  await load()
}
</script>

<template>
  <div>
    <h1>爬取账号（Cookie 池）</h1>
    <p class="muted">
      账号仅用于犇犇爬取。cookie 明文传入后加密存库。403/失效会自动禁用。
    </p>

    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>备注</th>
          <th>Luogu UID</th>
          <th>启用</th>
          <th>最近使用</th>
          <th>失败次数</th>
          <th>状态/停用原因</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="a in accounts" :key="a.id">
          <td>{{ a.id }}</td>
          <td>{{ a.label }}</td>
          <td>{{ a.luogu_uid }}</td>
          <td>
            <span :class="a.enabled ? 'ok' : 'no'">{{ a.enabled ? '✓' : '✗' }}</span>
          </td>
          <td class="muted small">{{ a.last_used_at || '-' }}</td>
          <td>{{ a.fail_count }}</td>
          <td>
            <code>{{ a.last_status || '-' }}</code>
            <div v-if="a.disabled_reason" class="muted small">{{ a.disabled_reason }}</div>
          </td>
          <td>
            <button @click="toggle(a)">
              {{ a.enabled ? '禁用' : '启用' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <section class="add-form">
      <h2>录入新账号</h2>
      <div class="form-grid">
        <label>备注 (label)<input v-model="form.label" placeholder="如: 主力1"></label>
        <label>Luogu UID<input v-model.number="form.luogu_uid" type="number"></label>
        <label>_uid（Cookie）<input v-model="form.uid_value"></label>
        <label>__client_id（Cookie）<input v-model="form.client_id"></label>
        <label>C3VK（Cookie，可选）<input v-model="form.c3vk"></label>
      </div>
      <button class="primary" :disabled="adding" @click="add">
        {{ adding ? '提交中...' : '添加' }}
      </button>
    </section>
  </div>
</template>

<style scoped>
table { width: 100%; border-collapse: collapse; margin-top: 16px; }
th, td {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
.ok { color: var(--lg-green); }
.no { color: var(--lg-red); }
.muted { color: var(--text-muted); }
.small { font-size: 13px; }
.add-form {
  margin-top: 30px;
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}
.form-grid label { display: block; }
.form-grid input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  margin-top: 4px;
  box-sizing: border-box;
}
button {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--surface);
  cursor: pointer;
}
button.primary {
  margin-top: 12px;
  background: var(--link);
  color: white;
  border: none;
  padding: 8px 20px;
}
</style>
