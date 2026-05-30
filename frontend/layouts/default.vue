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

// 运行天数：以 2026-05-01 为元年。客户端 + 服务端都按 UTC 算保证 SSR 一致。
const runDays = computed(() => {
  const start = Date.UTC(2026, 4, 1)
  const today = new Date()
  const todayUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())
  return Math.max(1, Math.floor((todayUtc - start) / 86400000) + 1)
})

const QQ_GROUP_URL = 'https://qun.qq.com/universal-share/share?ac=1&authKey=DNGeuTd%2FO6sVz5sPqBBv0pZmNZYnf4lg6AL4oeWyXyB3Cb2siArgWUMmaJVKrg6H&busi_data=eyJncm91cENvZGUiOiIxMDU5MzYxNjY4IiwidG9rZW4iOiJHVDk4VCtIOXFaOFdwVGlzR1lIYnVFRUVXZWplRE03a3Z1amNldWdramF5bGl2aDRkTmdmUlkrQWIrZ0xGd2FBIiwidWluIjoiMjQ3NjY3NDU5In0%3D&data=rP1H0BOgnlMi849TXTLTjawGLdZpsX8le6DR_jykWjKBi0elXkJVFrH9UuBejb5fMhL9DzrOEdOizmp6S_Knqw&svctype=4&tempid=h5_group_info'

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
]
</script>

<template>
  <div class="layout-root">
    <aside class="side-nav">
      <NuxtLink to="/" class="brand" title="洛谷档案馆">
        <img src="/favicon.png" alt="洛谷档案馆" class="brand-logo">
        <span class="label">洛谷档案馆</span>
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
        <div class="footer-inner">
          <div class="footer-col">
            <div class="footer-line">© 2026 洛谷档案馆</div>
            <div class="footer-line">已运行 {{ runDays }} 天</div>
            <div class="footer-line">第三方存档，与洛谷官方无关，所有内容版权归原作者</div>
          </div>
          <div class="footer-col">
            <div class="footer-line">
              <a :href="QQ_GROUP_URL" target="_blank" rel="noopener noreferrer">
                QQ 群 1059361668
              </a>
            </div>
            <div class="footer-line">
              <a href="https://github.com/px-poxiao/luogu-archive" target="_blank" rel="noopener noreferrer">
                GitHub
              </a>
            </div>
            <div class="footer-line">
              <NuxtLink to="/takedown">侵权投诉 / 内容删除</NuxtLink>
            </div>
          </div>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.layout-root {
  min-height: 100vh;
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

.brand-logo {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 7px;
  object-fit: cover;
  display: block;
  margin-left: -4px;
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
  margin-left: 56px;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  min-width: 0;
}
.main-area {
  flex: 1;
  padding: 28px 40px 56px;
}
.site-footer {
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: 14px 0;
  font-size: 14px;
  color: var(--text-muted);
  /* 横跨整个 viewport（拉出 layout-body 的 margin-left:56），
     左 56 段被 fixed 边栏盖在上面 —— 视觉上 footer 下"穿过"边栏，
     左右各 53px padding 对称（≈ 2 倍行高）。 */
  margin-left: -56px;
}
.footer-inner {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  /* 左 padding = 边栏宽 56 + 53（2 倍行高）；右 53。视觉上左栏离边栏右沿 53px。 */
  padding: 0 53px 0 109px;
  gap: 16px;
  flex-wrap: wrap;
}
.footer-col {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: left;
  line-height: 1.9;
}
.footer-line a {
  color: var(--text-muted);
}
.footer-line a:hover {
  color: var(--link);
}

/* 左侧栏在所有设备（含手机端）保持一致 —— 56px 宽固定贴左
   layout-body 永远 margin-left:56，footer 已自行 -56 抵消撑满 */
</style>
