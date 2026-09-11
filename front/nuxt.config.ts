import tailwindcss from '@tailwindcss/vite'

// 정보처리기사 필기 학습 앱 — SPA(ssr:false) + Tailwind CSS v4.
// dev 서버 포트는 백엔드 기본 CORS 허용 오리진(http://localhost:8091)과 맞춘다(back/README.md).
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: false },
  ssr: false,
  devServer: { port: 8091 },
  css: ['~/assets/css/main.css'],
  vite: { plugins: [tailwindcss()] },
  runtimeConfig: {
    public: {
      // FastAPI 백엔드 오리진. 배포·다른 포트에서는 NUXT_PUBLIC_API_BASE 로 덮어쓴다.
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://127.0.0.1:8092',
    },
  },
  app: {
    head: {
      htmlAttrs: { lang: 'ko' },
      title: '정보처리기사 필기',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: '정보처리기사 필기 기출문제 — 과목별 학습 사이클' },
      ],
      link: [{ rel: 'icon', href: '/favicon.ico' }],
    },
  },
})
