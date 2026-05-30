<!-- 管理后台专用布局，比前台简洁 -->
<script setup lang="ts">
const admin = useAdminStore()
function logout() {
  admin.clear()
  navigateTo('/admin/login')
}
</script>

<template>
  <div class="admin-root">
    <header>
      <div class="inner">
        <NuxtLink to="/admin" class="brand">洛谷档案馆 · 管理后台</NuxtLink>
        <nav v-if="admin.isLoggedIn">
          <NuxtLink to="/admin">仪表盘</NuxtLink>
          <NuxtLink to="/admin/takedowns">删除申请</NuxtLink>
          <NuxtLink to="/admin/accounts">爬取账号</NuxtLink>
          <NuxtLink to="/admin/problems">题库刷新</NuxtLink>
          <NuxtLink to="/admin/audit">审计日志</NuxtLink>
        </nav>
        <div v-if="admin.isLoggedIn" class="right">
          <span>{{ admin.displayName }}</span>
          <button @click="logout">登出</button>
        </div>
      </div>
    </header>
    <main>
      <slot />
    </main>
  </div>
</template>

<style scoped>
.admin-root { min-height: 100vh; }
header {
  background: #222;
  color: #eee;
  padding: 10px 0;
}
.inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 20px;
}
.brand { color: #fff; font-weight: 700; }
nav { display: flex; gap: 16px; flex: 1; }
nav a { color: #ddd; }
.right { display: flex; gap: 10px; align-items: center; }
.right button {
  background: none;
  color: #ddd;
  border: 1px solid #555;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}
main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px 16px;
}
</style>
