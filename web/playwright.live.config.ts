import { defineConfig, devices } from "@playwright/test";
import process from "node:process";

const CI = process.env["CI"] === "true";

// The workflow owns the real PostGIS-backed API and the production Vite preview.
// Playwright deliberately starts neither and never substitutes a browser-specific
// executable path: the installed @playwright/test runtime selects its own Chromium.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /live_integration\.spec\.ts/,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  retries: CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env["LIVE_BASE_URL"] ?? "http://127.0.0.1:4173",
    serviceWorkers: "block",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "live-chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
