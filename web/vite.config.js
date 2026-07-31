import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  // Two pages, not two apps. `/` is the support chat; `/chat-widget` is a Cadre-styled mockup with
  // the same bot as a floating widget, to show how it would actually be embedded.
  //
  // Vite emits ABSOLUTE asset paths (`/assets/index-….js`). Those resolve correctly from
  // `/chat-widget/` because FastAPI mounts the bundle at `/` — so there is deliberately no `base`
  // set here, and adding one would break the root page.
  //
  // FastAPI needs no route for the second page: `StaticFiles(html=True)` resolves a directory to
  // its index.html, so `dist/chat-widget/index.html` is served at `/chat-widget` for free.
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        'chat-widget': resolve(__dirname, 'chat-widget/index.html'),
      },
    },
  },
  // In dev the UI runs on :5173 and the API on :8000. In production both are the same
  // origin (FastAPI serves this bundle), which is why there is no CORS config anywhere.
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
