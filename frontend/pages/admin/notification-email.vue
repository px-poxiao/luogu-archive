<script setup lang="ts">
definePageMeta({ layout: 'admin' })
const admin=useAdminStore(); const api=useAdminApi(); const email=ref(''); const verified=ref(false); const message=ref('')
onMounted(async()=>{if(!admin.isLoggedIn)return navigateTo('/admin/login');const data=await api<any>('/admin/notification-email');email.value=data.email||'';verified.value=data.verified})
async function submit(){const data=await api<any>('/admin/notification-email',{method:'POST',body:{email:email.value}});message.value=data.message;verified.value=false}
</script>
<template><div class="email-page"><h1>管理员通知邮箱</h1><p>验证后的邮箱会收到插件推荐、删除和举报通知。邮件发送失败不会回滚申请。</p><form @submit.prevent="submit"><label>通知邮箱<input v-model.trim="email" type="email" required></label><span :class="verified?'ok':'pending'">{{verified?'已验证':'未验证'}}</span><button>发送验证邮件</button></form><p v-if="message" class="message">{{message}}</p></div></template>
<style scoped>
h1{margin-top:0}.email-page>p{color:var(--text-muted)}form{display:flex;align-items:flex-end;gap:10px;margin-top:20px}label{display:grid;gap:6px;min-width:320px}input,button{border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text);padding:8px 10px;font:inherit}button{background:var(--link);border-color:var(--link);color:#fff;cursor:pointer}.ok{color:var(--lg-green)}.pending{color:var(--lg-orange)}.message{padding:10px;border-left:3px solid var(--link)}@media(max-width:600px){form{align-items:stretch;flex-direction:column}label{min-width:0}}
</style>
