import { defineConfig, devices } from "@playwright/test";

// Separate config: the repo's projects are scoped to the accessibility specs,
// and this run needs the already-running preview server (mocks disabled)
// rather than the dev server the main config starts.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /live_integration\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  use: { baseURL: process.env.LIVE_BASE_URL ?? "http://127.0.0.1:4173", serviceWorkers: "allow" },
  projects: [
    {
      name: "live",
      use: {
        ...devices["Desktop Chrome"],
        // The sandbox ships Chromium for a different Playwright build, and
        // downloading another is blocked. Point at the installed one instead.
        launchOptions: { executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" },
      },
    },
  ],
});
