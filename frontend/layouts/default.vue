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

// 左侧导航项。icon 为内联 SVG path（24x24 viewBox）
const navItems = [
  {
    to: '/',
    label: '首页',
    icon: 'M3 12L12 3l9 9M5 10v10h14V10',
  },
  {
    to: '/feed',
    label: '伪全网犇',
    icon: 'M4 5h16v10H7l-3 3V5z',
  },
  {
    to: '/judgement',
    label: '陶片放逐',
    icon: 'M4 14l6-6 4 4 6-6M4 20h16',
  },
  {
    to: '/problem/list',
    label: '题目',
    icon: 'M6 4h10l4 4v12H6V4zM9 14h6M9 18h6',
  },
  {
    to: '/takedown',
    label: '侵权删除',
    icon: 'M12 3l8 4v6c0 5-4 7-8 8-4-1-8-3-8-8V7l8-4z',
  },
]
</script>

<template>
  <div class="layout-root">
    <aside class="side-nav">
      <NuxtLink to="/" class="brand" title="洛谷存档">
        <svg viewBox="0 0 24 24" class="icon">
          <path
            d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linejoin="round"
          />
        </svg>
        <span class="label">洛谷存档</span>
      </NuxtLink>

      <nav class="nav-items">
        <NuxtLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :title="item.label"
        >
          <svg viewBox="0 0 24 24" class="icon">
            <path
              :d="item.icon"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <span class="label">{{ item.label }}</span>
        </NuxtLink>
      </nav>

      <div class="side-bottom">
        <template v-if="auth.isLoggedIn">
          <NuxtLink to="/me" class="nav-item" :title="auth.displayName || '我的关注'">
            <svg viewBox="0 0 24 24" class="icon">
              <path
                d="M12 12a4 4 0 100-8 4 4 0 000 8zM4 20c0-4 4-6 8-6s8 2 8 6"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span class="label">{{ auth.displayName || '我的关注' }}</span>
          </NuxtLink>
          <button class="nav-item as-btn" title="登出" @click="logout">
            <svg viewBox="0 0 24 24" class="icon">
              <path
                d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span class="label">登出</span>
          </button>
        </template>
        <template v-else>
          <NuxtLink to="/login" class="nav-item" title="登录">
            <svg viewBox="0 0 24 24" class="icon">
              <path
                d="M10 4H5v16h5M14 8l4 4-4 4M8 12h10"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span class="label">登录</span>
          </NuxtLink>
          <NuxtLink to="/register" class="nav-item" title="注册">
            <svg viewBox="0 0 24 24" class="icon">
              <path
                d="M12 12a4 4 0 100-8 4 4 0 000 8zM4 20c0-4 4-6 8-6M17 16v6M14 19h6"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span class="label">注册</span>
          </NuxtLink>
        </template>

        <button class="nav-item as-btn" :title="colorMode.value === 'dark' ? '切换浅色' : '切换深色'" @click="toggle">
          <svg v-if="colorMode.value === 'dark'" viewBox="0 0 24 24" class="icon">
            <circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2" />
            <path
              d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
            />
          </svg>
          <svg v-else viewBox="0 0 24 24" class="icon">
            <path
              d="M21 13A9 9 0 1111 3a7 7 0 0010 10z"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linejoin="round"
            />
          </svg>
          <span class="label">{{ colorMode.value === 'dark' ? '浅色模式' : '深色模式' }}</span>
        </button>
      </div>
    </aside>

    <div class="layout-body">
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
  </div>
</template>

<style scoped>
.layout-root {
  min-height: 100vh;
  display: flex;
}

/* 左侧悬停展开导航栏 */
.side-nav {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: 56px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 10px 8px;
  gap: 4px;
  z-index: 20;
  overflow: hidden;
  transition: width 0.18s ease;
}
.side-nav:hover {
  width: 200px;
  box-shadow: 2px 0 12px rgba(0, 0, 0, 0.06);
}

.brand,
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 10px;
  color: var(--text);
  text-decoration: none;
  border-radius: 6px;
  font-size: 14px;
  white-space: nowrap;
  transition: background 0.15s;
  background: none;
  border: none;
  cursor: pointer;
  font: inherit;
  text-align: left;
  width: 100%;
}
.brand { font-weight: 700; font-size: 15px; margin-bottom: 6px; }
.nav-item:hover,
.brand:hover {
  background: var(--hover);
  text-decoration: none;
}
.nav-item.router-link-active {
  background: var(--hover);
  color: var(--link);
}

.icon {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  color: inherit;
}

.label {
  opacity: 0;
  transform: translateX(-4px);
  transition: opacity 0.15s ease, transform 0.18s ease;
  pointer-events: none;
}
.side-nav:hover .label {
  opacity: 1;
  transform: translateX(0);
  pointer-events: auto;
}

.nav-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.side-bottom {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

/* 主体 */
.layout-body {
  flex: 1;
  min-width: 0;
  margin-left: 56px;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}
.main-area {
  flex: 1;
  padding: 28px 40px 56px;
}
.site-footer {
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: 16px 0;
  font-size: 14px;
  color: var(--text-muted);
  text-align: center;
}

/* 移动端：导航栏直接固定在底部（老做法，简单粗暴） */
@media (max-width: 640px) {
  .side-nav {
    top: auto;
    right: 0;
    bottom: 0;
    width: auto;
    height: auto;
    flex-direction: row;
    padding: 6px;
    border-right: none;
    border-top: 1px solid var(--border);
    overflow-x: auto;
  }
  .side-nav:hover { width: auto; box-shadow: none; }
  .brand { display: none; }
  .side-bottom {
    flex-direction: row;
    margin-top: 0;
    padding-top: 0;
    border-top: none;
    border-left: 1px solid var(--border);
    padding-left: 6px;
    margin-left: 4px;
  }
  .label { display: none; }
  .layout-body { margin-left: 0; padding-bottom: 60px; }
}
</style>
