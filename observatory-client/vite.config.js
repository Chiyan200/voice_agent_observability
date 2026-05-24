import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Optional: proxy API calls to avoid CORS issues in dev
      // '/api': { target: 'http://localhost:8000', changeOrigin: true, rewrite: path => path.replace(/^\/api/, '') }
    }
  }
})