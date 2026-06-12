import { defineConfig } from 'vitest/config'
import { resolve } from 'path'

export default defineConfig({
  resolve: {
    alias: {
      '~': resolve(__dirname, '.'),
      '#app': resolve(__dirname, 'node_modules/nuxt/dist/app'),
    },
  },
  test: {
    environment: 'node',
    exclude: ['tests/e2e/**', 'node_modules/**'],
  },
})
