<script setup lang="ts">
import type { PluginTag } from '~/types/plugin'
definePageMeta({ layout: 'admin' })
const admin = useAdminStore()
const api = useAdminApi()
const rows = ref<PluginTag[]>([])
const newName = ref('')

async function load() { rows.value = await api('/admin/plugin-tags') }
async function createTag() {
  if (!newName.value.trim()) return
  await api('/admin/plugin-tags', { method: 'POST', body: { name: newName.value, is_active: true, sort_order: rows.value.length + 1 } })
  newName.value = ''
  await load()
}
async function save(row: PluginTag) {
  await api(`/admin/plugin-tags/${row.id}`, { method: 'PUT', body: { name: row.name, is_active: row.is_active, sort_order: row.sort_order } })
  await load()
}
onMounted(async () => { if (!admin.isLoggedIn) return navigateTo('/admin/login'); await load() })
</script>

<template>
  <div><h1>插件标签</h1>
    <form class="new-tag" @submit.prevent="createTag"><input v-model.trim="newName" maxlength="32" placeholder="新标签名称"><button>新增标签</button></form>
    <table><thead><tr><th>名称</th><th>排序</th><th>启用</th><th>操作</th></tr></thead><tbody>
      <tr v-for="row in rows" :key="row.id"><td><input v-model.trim="row.name" maxlength="32"></td><td><input v-model.number="row.sort_order" type="number" min="0" max="10000"></td><td><input v-model="row.is_active" type="checkbox"></td><td><button @click="save(row)">保存</button></td></tr>
    </tbody></table>
  </div>
</template>

<style scoped>
h1{margin-top:0}.new-tag{display:flex;gap:8px;margin-bottom:18px}input,button{border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text);padding:7px 9px;font:inherit}button{cursor:pointer}.new-tag button{background:var(--link);color:#fff;border-color:var(--link)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--border)}th{background:var(--surface)}
</style>
