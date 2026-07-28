import { defineConfig, devices } from "@playwright/test";

// Browser end-to-end + axe accessibility. NEEDS a real browser, so it is NOT part of the
// unit CI job: run `npm run e2e:install` once, then `npm run e2e`. This is the gate that
// covers WebGL render, tiles, keyboard, and responsive behaviour that jsdom cannot.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  use: { baseURL: "http://localhost:5173", trace: "on-first-retry" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 5"] } },
  ],
});
