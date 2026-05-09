<script setup lang="ts">
const colorMode = useColorMode()
const auth = useAuthStore()
const api = useApi()

function toggle() {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}

async function logout() {
  try { await api('/auth/logout', { method: 'POST' }) } catch {}
  auth.clear()
  navigateTo('/')
}
</script>

<template>
  <div class="layout-root">
    <header class="site-header">
      <div class="container nav">
        <NuxtLink to="/" class="brand">洛谷存档</NuxtLink>
        <nav class="nav-links">
          <NuxtLink to="/feed">伪全网犇</NuxtLink>
          <NuxtLink to="/judgement">陶片放逐</NuxtLink>
          <NuxtLink to="/problem/list">题目</NuxtLink>
          <NuxtLink to="/takedown">侵权删除</NuxtLink>
        </nav>
        <div class="right">
          <template v-if="auth.isLoggedIn">
            <span class="hi">{{ auth.displayName }}</span>
            <NuxtLink to="/me">我的关注</NuxtLink>
            <button class="link-btn" @click="logout">登出</button>
          </template>
          <template v-else>
            <NuxtLink to="/login">登录</NuxtLink>
            <NuxtLink to="/register">注册</NuxtLink>
          </template>
          <button class="theme-btn" @click="toggle">
            {{ colorMode.value === 'dark' ? '☀' : '☾' }}
          </button>
        </div>
      </div>
    </header>

    <main class="container main-area">
      <slot />
    </main>

    <footer class="site-footer">
      <div class="container">
        本站为第三方存档，与洛谷官方无关，所有内容版权归原作者。
        <NuxtLink to="/takedown">侵权投诉 / 内容删除</NuxtLink>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.layout-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.site-header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
}
.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 12px 16px;
}
.brand {
  font-size: 20px;
  font-weight: 700;
  color: var(--text);
}
.nav-links {
  display: flex;
  gap: 20px;
  flex: 1;
}
.right {
  display: flex;
  gap: 12px;
  align-items: center;
}
.hi {
  color: var(--text-muted);
  font-size: 14px;
}
.link-btn {
  background: none;
  border: none;
  color: var(--link);
  cursor: pointer;
  font: inherit;
  padding: 0;
}
.theme-btn {
  background: none;
  border: 1px solid var(--border);
  border-radius: 50%;
  width: 36px;
  height: 36px;
  cursor: pointer;
  font-size: 18px;
  color: var(--text);
}
.main-area {
  flex: 1;
  padding: 20px 16px 40px;
}
.site-footer {
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: 16px 0;
  font-size: 14px;
  color: var(--text-muted);
  text-align: center;
}
</style>
