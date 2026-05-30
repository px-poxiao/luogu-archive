// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  // 开发工具
  devtools: { enabled: true },

  // 渲染模式：SSR（有利于 SEO 展示 + 首屏快）
  ssr: true,

  // 模块
  modules: [
    '@nuxtjs/color-mode',   // Dark Mode
    '@pinia/nuxt',          // 全局 store
    '@vueuse/nuxt',         // composition utilities
    '@nuxt/fonts',
  ],

  // 环境变量（服务端 + 客户端分开）
  runtimeConfig: {
    // 仅 Server 可见
    apiInternalUrl: process.env.NUXT_API_INTERNAL_URL || 'http://127.0.0.1:8000',
    public: {
      // 客户端也可见
      apiBaseUrl: process.env.NUXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
      siteName: '洛谷档案馆',
      captchaProvider: process.env.NUXT_PUBLIC_CAPTCHA_PROVIDER || 'turnstile',
      captchaSiteKey: process.env.NUXT_PUBLIC_CAPTCHA_SITE_KEY || '',
    },
  },

  colorMode: {
    preference: 'system',   // 默认跟随系统
    fallback: 'light',
    classSuffix: '',        // dark / light 直接做类名
  },

  css: ['~/assets/css/base.css', 'katex/dist/katex.min.css'],

  // 站点元信息
  app: {
    head: {
      htmlAttrs: { lang: 'zh-CN' },
      title: '洛谷档案馆',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'robots', content: 'noindex,nofollow,noarchive' }, // 合规底线：禁收录
        { name: 'description', content: '洛谷档案馆 —— 第三方存档：文章 / 剪贴板 / 犇犇 / 陶片放逐 / 题解' },
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
