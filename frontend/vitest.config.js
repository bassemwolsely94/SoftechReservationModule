import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Unit tests (test plan R8): `npm test`. Browser tests live in e2e/ and run with Playwright.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{js,jsx}'],
    restoreMocks: true,
    unstubGlobals: true,
  },
})
