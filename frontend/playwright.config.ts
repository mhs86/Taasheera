import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1, retries: 0,
  timeout: 30000, reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:5273', trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {} },
  webServer: {
    command: `${process.env.TAASHEERA_TEST_PYTHON || 'python'} ../backend/preview.py run --seed-demo --api-port 8100 --web-port 5273`,
    env: { TAASHEERA_PREVIEW_NAME: 'e2e-preview' },
    url: 'http://127.0.0.1:5273/sign-in', reuseExistingServer: false, timeout: 60000,
  },
})
