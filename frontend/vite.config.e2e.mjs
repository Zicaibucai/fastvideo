import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({ plugins: [react()], cacheDir: '/tmp/vite-cache-e2e', server: { port: 5173, host: '127.0.0.1', proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true }, '/files': { target: 'http://localhost:8000', changeOrigin: true } } } })
