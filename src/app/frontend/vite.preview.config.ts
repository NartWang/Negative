/// <reference types="vitest/config" />
// Preview-only config: keeps the committed vite.config.ts untouched while
// running this checkout beside another one (ports 3000/8000 are taken).
import { defineConfig, mergeConfig } from 'vite'
import base from './vite.config'

export default mergeConfig(
  base,
  defineConfig({
    server: {
      host: '127.0.0.1',
      port: 3010,
      strictPort: true,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8010',
          changeOrigin: true,
        },
      },
    },
  }),
)
