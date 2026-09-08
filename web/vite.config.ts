import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const apiUrl = env.NONO_API_URL || 'http://127.0.0.1:8000'
  return {
  plugins: [react()],
  build: { assetsDir: 'web-assets' },
  server: {
    port: 5173,
    proxy: {
      '/api': apiUrl,
      '/assets/so101': apiUrl,
    },
  },
  }
})
