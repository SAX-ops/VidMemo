export default defineNuxtConfig({
  devtools: { enabled: true },
  modules: ['@nuxtjs/tailwindcss'],
  css: ['~/assets/css/main.css'],
  app: {
    head: {
      title: '影记 VidMemo - 全平台视频下载 + AI 笔记',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: '全平台视频下载 + AI 笔记，支持 YouTube、B站、抖音等 10+ 平台，一键生成章节大纲、核心摘要和思维导图' }
      ],
      link: [
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' },
        // P0-4: Google Fonts (display=swap 避免 FOUT 阻塞渲染)
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&family=Space+Grotesk:wght@500;600;700&display=swap' },
      ]
    }
  },
  runtimeConfig: {
    public: {
      apiBase: 'http://localhost:8000'
    }
  }
})
