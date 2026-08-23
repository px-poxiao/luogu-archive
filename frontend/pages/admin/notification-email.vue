<script setup lang="ts">
definePageMeta({ layout: 'admin' })
const admin=useAdminStore(); const api=useAdminApi(); const email=ref(''); const message=ref('')
onMounted(async()=>{if(!admin.isLoggedIn)return navigateTo('/admin/login');const data=await api<any>('/admin/notification-email');email.value=data.email||''})
async function submit(){const data=await api<any>('/admin/notification-email',{method:'POST',body:{email:email.value}});message.value=data.message}
</script>
<template><div class="email-page"><h1>管理员通知邮箱</h1><p>保存后，该邮箱会收到插件推荐、删除和举报通知。邮件发送失败不会回滚申请。</p><form @submit.prevent="submit"><label>通知邮箱<input v-model.trim="email" type="email" required></label><button>保存</button></form><p v-if="message" class="message">{{message}}</p></div></template>
<style scoped>
h1{margin-top:0}.email-page>p{color:var(--text-muted)}form{display:flex;align-items:flex-end;gap:10px;margin-top:20px}label{display:grid;gap:6px;min-width:320px}input,button{border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text);padding:8px 10px;font:inherit}button{background:var(--link);border-color:var(--link);color:#fff;cursor:pointer}.message{padding:10px;border-left:3px solid var(--link)}@media(max-width:600px){form{align-items:stretch;flex-direction:column}label{min-width:0}}
</style>
