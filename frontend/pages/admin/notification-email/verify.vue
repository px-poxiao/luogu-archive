<script setup lang="ts">
definePageMeta({ layout: 'admin' })
const route=useRoute(); const config=useRuntimeConfig(); const message=ref('正在验证…'); const failed=ref(false)
onMounted(async()=>{try{const data=await $fetch<any>(`${config.public.apiBaseUrl||''}/api/v1/admin/notification-email/verify`,{query:{token:String(route.query.token||'')}});message.value=data.message}catch(error:any){failed.value=true;message.value=error?.data?.message||'验证失败'}})
</script>
<template><div class="verify"><h1>{{failed?'验证失败':'通知邮箱验证'}}</h1><p>{{message}}</p><NuxtLink to="/admin/notification-email">返回通知邮箱设置</NuxtLink></div></template>
<style scoped>.verify{max-width:600px;margin:60px auto;padding:24px;border:1px solid var(--border);text-align:center}.verify h1{margin-top:0}</style>
