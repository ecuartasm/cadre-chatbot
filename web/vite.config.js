import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // In dev the UI runs on :5173 and the API on :8000. In production both are the same
  // origin (FastAPI serves this bundle), which is why there is no CORS config anywhere.
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
