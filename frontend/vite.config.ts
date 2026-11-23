import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
const api = process.env.VITE_API_PROXY || 'http://127.0.0.1:8000'
export default defineConfig({ base: process.env.VITE_BASE_PATH || '/', plugins: [react()], server: { proxy: { '/api': api, '/health': api } } })
