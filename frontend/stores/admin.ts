/**
 * 管理员会话状态（单独 store，独立于站内用户）。
 * access token 放内存；刷新页面丢失，需重新登录（频率低不值得做 refresh）。
 */
import { defineStore } from 'pinia'

export const useAdminStore = defineStore('admin', {
  state: () => ({
    accessToken: null as string | null,
    expiresAt: 0,
    username: '',
    displayName: '',
  }),
  getters: {
    isLoggedIn: (s) => !!s.accessToken && s.expiresAt > Date.now(),
  },
  actions: {
    setToken(data: { access_token: string; expires_in: number; username: string; display_name: string }) {
      this.accessToken = data.access_token
      this.expiresAt = Date.now() + data.expires_in * 1000 - 10_000
      this.username = data.username
      this.displayName = data.display_name
    },
    clear() {
      this.accessToken = null
      this.expiresAt = 0
      this.username = ''
      this.displayName = ''
    },
  },
})
