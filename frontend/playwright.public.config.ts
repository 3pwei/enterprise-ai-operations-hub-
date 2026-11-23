import { defineConfig } from '@playwright/test'

export default defineConfig({ testDir: 'tests', testMatch: 'public.spec.ts', timeout: 90000,
  use: { baseURL: process.env.PUBLIC_DEMO_URL ?? 'http://127.0.0.1',
    launchOptions: { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH },
    trace: 'retain-on-failure' } })
