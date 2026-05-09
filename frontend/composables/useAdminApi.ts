/**
 * 管理后台专用 API 客户端，附加管理员 Authorization。
 */
export const useAdminApi = () => {
  const config = useRuntimeConfig()
  const base = import.meta.server
    ? config.apiInternalUrl
    : config.public.apiBaseUrl

  return $fetch.create({
    baseURL: `${base}/api/v1`,
    onRequest({ options }) {
      if (import.meta.client) {
        const admin = useAdminStore()
        if (admin.accessToken) {
          options.headers = {
            ...(options.headers as any),
            Authorization: `Bearer ${admin.accessToken}`,
          }
        }
      }
    },
  })
}
