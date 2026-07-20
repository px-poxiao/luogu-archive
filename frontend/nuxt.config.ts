export default defineNuxtConfig({
  devtools: { enabled: true },
  ssr: true,
  modules: [
    '@nuxtjs/color-mode',
    '@pinia/nuxt',
    '@vueuse/nuxt',
    '@nuxt/fonts',
  ],
  runtimeConfig: {
    apiInternalUrl:
      process.env.NUXT_API_INTERNAL_URL
      || `http://127.0.0.1:${process.env.WEB_PORT || '8001'}`,
    public: {
      apiBaseUrl: process.env.NUXT_PUBLIC_API_BASE_URL || '',
      siteName: '\u6d1b\u8c37\u6863\u6848\u9986',
      captchaProvider: process.env.NUXT_PUBLIC_CAPTCHA_PROVIDER || 'turnstile',
      captchaSiteKey: process.env.NUXT_PUBLIC_CAPTCHA_SITE_KEY || '',
      captchaAliyunPrefix: process.env.NUXT_PUBLIC_CAPTCHA_ALIYUN_PREFIX || '',
      captchaAliyunSceneId: process.env.NUXT_PUBLIC_CAPTCHA_ALIYUN_SCENE_ID || '',
      captchaAliyunRegion: process.env.NUXT_PUBLIC_CAPTCHA_ALIYUN_REGION || 'cn',
    },
  },
  colorMode: {
    preference: 'system',
    fallback: 'light',
    classSuffix: '',
  },
  css: ['~/assets/css/base.css', 'katex/dist/katex.min.css'],
  routeRules: {
    '/favicon.png': {
      headers: {
        'cache-control': 'public, max-age=604800, stale-while-revalidate=86400',
      },
    },
  },
  app: {
    head: {
      htmlAttrs: { lang: 'zh-CN' },
      title: '\u6d1b\u8c37\u6863\u6848\u9986',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'robots', content: 'noindex,nofollow,noarchive' },
        {
          name: 'description',
          content: '\u6d1b\u8c37\u6863\u6848\u9986 - \u7b2c\u4e09\u65b9\u5b58\u6863\uff1a\u6587\u7ae0 / \u526a\u8d34\u677f / \u7287\u7287 / \u9676\u7247\u653e\u9010 / \u9898\u89e3',
        },
      ],
      link: [
        { rel: 'icon', type: 'image/png', href: '/favicon.png' },
      ],
    },
  },
  typescript: {
    strict: true,
  },
  compatibilityDate: '2026-05-01',
})
