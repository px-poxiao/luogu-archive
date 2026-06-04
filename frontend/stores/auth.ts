/**
 * 认证状态管理（Pinia store）。
 *
 * access token 放内存（刷新页面丢失，靠 refresh cookie 重新换）。
 * 前端初始化时调 /auth/refresh，用 refresh cookie 恢复登录态。
 */
import { defineStore } from 'pinia'

interface AuthState {
  accessToken: string | null
  expiresAt: number           // ms 时间戳
  displayName: string
  email: string
  emailVerified: boolean
  initialized: boolean
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    accessToken: null,
    expiresAt: 0,
    displayName: '',
    email: '',
    emailVerified: false,
    initialized: false,
  }),
  getters: {
    isLoggedIn: (s) => !!s.accessToken && s.expiresAt > Date.now(),
  },
  actions: {
    setTokens(data: {
      access_token: string
      expires_in: number
      display_name: string
      email: string
      email_verified: boolean
    }) {
      this.accessToken = data.access_token
      this.expiresAt = Date.now() + data.expires_in * 1000 - 10_000 // 提前 10s 视为过期
      this.displayName = data.display_name
      this.email = data.email
      this.emailVerified = data.email_verified
      if (import.meta.client) {
        localStorage.setItem('la_logged', '1')
      }
    },
    clear() {
      this.accessToken = null
      this.expiresAt = 0
      this.displayName = ''
      this.email = ''
      this.emailVerified = false
      this.initialized = true
      if (import.meta.client) {
        localStorage.removeItem('la_logged')
      }
    },
    async tryRefresh() {
      if (import.meta.server) return
      if (this.accessToken && this.expiresAt > Date.now()) {
        this.initialized = true
        return
      }
      try {
        const api = useApi()
        const data = await api<any>('/auth/refresh', { method: 'POST' })
        this.setTokens(data)
      } catch {
        this.clear()
      } finally {
        this.initialized = true
      }
    },
  },
})
