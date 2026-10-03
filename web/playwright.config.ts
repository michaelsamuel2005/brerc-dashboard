import { defineConfig, devices } from '@playwright/test';
import { a11yProjects } from './e2e/playwright.viewports';

const CI = process.env['CI'] === 'true';

export default defineConfig({
  testDir: './e2e',
  testIgnore: /serialization\.pw\.test\.ts/,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  ...(CI ? { workers: 2, retries: 1 } : { retries: 0 }),
  reporter: CI
    ? [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]]
    : [['list']],
  webServer: {
    command:
      'VITE_A11Y_TEST_MODE=true npm run dev -- --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !CI,
    timeout: 90_000
  },
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    serviceWorkers: 'allow'
  },
  projects: [
    {
      name: 'app-desktop-chromium',
      testMatch: /a11y\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] }
    },
    {
      name: 'app-mobile-chromium',
      testMatch: /a11y\.spec\.ts/,
      use: { ...devices['Pixel 5'] }
    },
    ...a11yProjects
  ]
});
