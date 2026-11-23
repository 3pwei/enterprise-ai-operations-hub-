import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: 'tests',
  testMatch: 'live.spec.ts',
  timeout: 90000,
  use: { baseURL: process.env.LIVE_UI_URL ?? 'http://127.0.0.1:5173',
    launchOptions: { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH }, trace: 'retain-on-failure' },
})
