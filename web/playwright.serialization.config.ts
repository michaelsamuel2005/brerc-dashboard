import { defineConfig } from '@playwright/test';

const executablePath = process.env['CHROMIUM_PATH'];

export default defineConfig({
  testDir: './e2e',
  testMatch: /serialization\.pw\.test\.ts/,
  reporter: [['list']],
  use: {
    launchOptions: executablePath ? { executablePath } : {}
  }
});
