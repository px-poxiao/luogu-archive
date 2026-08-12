<script setup lang="ts">
definePageMeta({ layout: 'admin' })
const admin = useAdminStore(); const api = useAdminApi()
const status = ref('pending'); const rows = ref<any[]>([])
const typeNames: Record<string,string> = { dangerous_request:'危险请求', malicious_code:'恶意代码', broken:'失效', copyright:'侵权', misleading:'信息不实', other:'其他' }
const statusNames: Record<string,string> = { pending:'待处理', resolved:'已解决', dismissed:'已驳回' }
async function load(){ rows.value = await api('/admin/plugin-reports',{query:{status:status.value}}) }
async function handle(id:number,next:'resolved'|'dismissed'){ const note=prompt('处理备注（可留空）：')||''; await api(`/admin/plugin-reports/${id}/handle`,{method:'POST',body:{status:next,admin_note:note}}); await load() }
onMounted(async()=>{ if(!admin.isLoggedIn)return navigateTo('/admin/login'); await load() }); watch(status,()=>void load())
</script>

<template><div><h1>插件举报</h1><select v-model="status"><option value="pending">待处理</option><option value="resolved">已解决</option><option value="dismissed">已驳回</option><option value="all">全部</option></select>
  <div class="reports"><article v-for="row in rows" :key="row.id"><header><strong>#{{row.id}} {{typeNames[row.report_type]}}</strong><span>{{statusNames[row.status] || row.status}}</span></header><p>{{row.description}}</p><small>插件 #{{row.plugin_id}} · 举报人 #{{row.reporter_user_id}} · {{row.created_at}}</small><footer v-if="row.status==='pending'"><button @click="handle(row.id,'dismissed')">驳回</button><button class="ok" @click="handle(row.id,'resolved')">标记解决</button></footer></article><p v-if="!rows.length">暂无举报</p></div>
</div></template>

<style scoped>
h1{margin-top:0}select,button{border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text);padding:7px 9px}.reports{margin-top:15px;border-top:1px solid var(--border)}article{padding:14px 2px;border-bottom:1px solid var(--border)}article header,article footer{display:flex;justify-content:space-between;gap:10px}article p{white-space:pre-wrap}small,header span{color:var(--text-muted)}footer{justify-content:flex-end!important;margin-top:10px}button{cursor:pointer}.ok{background:var(--lg-green);border-color:var(--lg-green);color:#fff}
</style>
