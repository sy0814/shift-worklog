import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  // 构建产物直接放到后端 static/，由 FastAPI 统一提供
  build: { outDir: '../backend/static', emptyOutDir: true },
})
