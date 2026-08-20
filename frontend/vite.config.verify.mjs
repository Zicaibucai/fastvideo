import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({ plugins: [react()], cacheDir: '/tmp/vite-cache-verify', build: { outDir: '/tmp/vite_out_verify3', emptyOutDir: true } })
