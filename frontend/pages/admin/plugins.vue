<script setup lang="ts">
import type { PluginSnapshot, PluginTag } from '~/types/plugin'

definePageMeta({ layout: 'admin' })
const admin = useAdminStore()
const api = useAdminApi()

const rows = ref<any[]>([])
const tags = ref<PluginTag[]>([])
const editing = ref<any>(null)
const versionSnapshot = ref<PluginSnapshot | null>(null)
const showVersionForm = ref(false)
const message = ref('')

async function load() {
  ;[rows.value, tags.value] = await Promise.all([
    api('/admin/plugins'),
    api('/admin/plugin-tags'),
  ])
}

function beginEdit(row: any) {
  editing.value = structuredClone(row)
  showVersionForm.value = false
}

async function saveMetadata() {
  await api(`/admin/plugins/${editing.value.id}`, {
    method: 'PUT',
    body: {
      name: editing.value.name,
      summary: editing.value.summary,
      is_official: editing.value.is_official,
      is_recommended: editing.value.is_recommended,
      tag_ids: editing.value.tags.map((tag: any) => tag.id),
    },
  })
  message.value = '插件信息已更新'
  await load()
}

function toggleTag(tag: PluginTag, checked: boolean) {
  const selected = new Map(editing.value.tags.map((item: PluginTag) => [item.id, item]))
  checked ? selected.set(tag.id, tag) : selected.delete(tag.id)
  editing.value.tags = [...selected.values()]
}

async function prepareVersion() {
  const data = await api<any>(`/admin/plugins/${editing.value.id}`)
  versionSnapshot.value = data.snapshot
  versionSnapshot.value!.version = ''
  versionSnapshot.value!.last_verified_on = new Date().toISOString().slice(0, 10)
  showVersionForm.value = true
}

async function publishVersion() {
  if (!versionSnapshot.value || !confirm('确认直接发布这个新代码版本吗？')) return
  await api(`/admin/plugins/${editing.value.id}/versions`, { method: 'POST', body: versionSnapshot.value })
  message.value = '新代码版本已发布'
  showVersionForm.value = false
  await load()
}

async function changeListed(row: any) {
  if (row.is_listed) {
    const reason = prompt('请填写下架原因：')
    if (!reason) return
    await api(`/admin/plugins/${row.id}/unlist`, { method: 'POST', body: { reason } })
  } else {
    await api(`/admin/plugins/${row.id}/restore`, { method: 'POST' })
  }
  await load()
  if (editing.value?.id === row.id) editing.value = null
}

onMounted(async () => {
  if (!admin.isLoggedIn) return navigateTo('/admin/login')
  await load()
})
</script>

<template>
  <div>
    <h1>插件管理</h1>
    <p v-if="message" class="message">{{ message }}</p>
    <div class="workspace">
      <div class="plugin-table">
        <table>
          <thead><tr><th>插件</th><th>状态</th><th>徽章</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td><strong>{{ row.name }}</strong><br><small>{{ row.article_id }}</small></td>
              <td>{{ row.is_listed ? '公开' : '已下架' }}</td>
              <td>{{ [row.is_official ? '官方' : '', row.is_recommended ? '推荐' : ''].filter(Boolean).join('、') || '-' }}</td>
              <td><button @click="beginEdit(row)">编辑</button><button @click="changeListed(row)">{{ row.is_listed ? '下架' : '恢复' }}</button></td>
            </tr>
          </tbody>
        </table>
      </div>

      <section v-if="editing" class="edit-pane">
        <h2>编辑 {{ editing.name }}</h2>
        <label>名称<input v-model.trim="editing.name" maxlength="80"></label>
        <label>简介<textarea v-model.trim="editing.summary" rows="3" maxlength="300" /></label>
        <fieldset><legend>可信度徽章</legend>
          <label class="inline"><input v-model="editing.is_official" type="checkbox">官方插件</label>
          <label class="inline"><input v-model="editing.is_recommended" type="checkbox">推荐插件</label>
        </fieldset>
        <fieldset><legend>功能标签</legend><div class="tag-list">
          <label v-for="tag in tags" :key="tag.id" class="inline">
            <input type="checkbox" :checked="editing.tags.some((item: any) => item.id === tag.id)" @change="toggleTag(tag, ($event.target as HTMLInputElement).checked)">{{ tag.name }}
          </label>
        </div></fieldset>
        <div class="actions"><button @click="saveMetadata">保存信息</button><button @click="prepareVersion">创建代码版本</button></div>

        <form v-if="showVersionForm && versionSnapshot" class="version-form" @submit.prevent="publishVersion">
          <h2>创建不可变代码版本</h2>
          <PluginSnapshotForm v-model="versionSnapshot" :tags="tags" admin-fields />
          <button type="submit" class="publish">直接发布新版本</button>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
h1 { margin-top: 0; }.workspace { display: grid; grid-template-columns: minmax(420px, .9fr) minmax(0, 1.1fr); gap: 20px; }
table { width: 100%; border-collapse: collapse; }th, td { padding: 9px; border-bottom: 1px solid var(--border); text-align: left; }th { background: var(--surface); }td button { margin-right: 6px; }
button { border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--text); padding: 6px 10px; cursor: pointer; }
.edit-pane { min-width: 0; padding: 18px; border: 1px solid var(--border); }.edit-pane > label { display: grid; gap: 6px; margin-bottom: 13px; }
input, textarea { border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--text); padding: 8px; font: inherit; }
fieldset { margin: 14px 0; border: 1px solid var(--border); }.inline { display: inline-flex; align-items: center; gap: 6px; margin-right: 16px; }.tag-list { display: flex; flex-wrap: wrap; gap: 8px; }
.actions { display: flex; gap: 9px; }.actions button:first-child, .publish { border-color: var(--link); background: var(--link); color: #fff; }
.version-form { margin-top: 24px; padding-top: 22px; border-top: 2px solid var(--border); }.publish { margin-top: 22px; padding: 9px 16px; }.message { padding: 8px 12px; border-left: 3px solid var(--lg-green); }
small { color: var(--text-muted); }@media (max-width: 900px) { .workspace { grid-template-columns: 1fr; } }
</style>
