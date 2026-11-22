import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.js',
      registerType: 'prompt',
      injectRegister: false, // 在 main.js 里自己注册，以便提示「有新版本」
      injectManifest: { globPatterns: ['**/*.{js,css,html,png,svg,woff2}'], maximumFileSizeToCacheInBytes: 4 * 1024 * 1024 },
      includeAssets: ['favicon.png', 'icons/apple-touch-icon.png'],
      manifest: {
        name: '工作记录 · Radni dnevnik',
        short_name: '工作记录',
        description: '交接班与工作记录 / Primopredaja smene i radni dnevnik',
        lang: 'zh',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#f4f5f7',
        theme_color: '#1f2d3d',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    host: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  // 构建产物直接放到后端 static/，由 FastAPI 统一提供
  build: { outDir: '../backend/static', emptyOutDir: true },
})
