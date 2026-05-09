/**
 * 应用启动时尝试用 refresh cookie 换取 access token。
 */
export default defineNuxtPlugin(async () => {
  if (import.meta.server) return
  const auth = useAuthStore()
  await auth.tryRefresh()
})
