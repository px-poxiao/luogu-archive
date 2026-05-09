/**
 * API 客户端。
 * 服务端 SSR 用 apiInternalUrl（内网地址更快）
 * 浏览器用 apiBaseUrl
 * 自动附加 Authorization: Bearer <token>（若已登录）
 */
export const useApi = () => {
  const config = useRuntimeConfig()

  // SSR 服务端走 internal，否则走 public
  const base = import.meta.server
    ? config.apiInternalUrl
    : config.public.apiBaseUrl

  return $fetch.create({
    baseURL: `${base}/api/v1`,
    credentials: 'include',
    onRequest({ options }) {
      // 仅浏览器端附加 auth header（SSR 时还没登录态）
      if (import.meta.client) {
        const auth = useAuthStore()
        if (auth.accessToken) {
          options.headers = {
            ...(options.headers as any),
            Authorization: `Bearer ${auth.accessToken}`,
          }
        }
      }
    },
    onResponseError({ response }) {
      console.warn('[api] error', response.status, response._data)
    },
  })
}
