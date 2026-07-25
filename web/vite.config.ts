/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The public front-end build. dev/test run entirely against the MSW mock (A11);
// production points at the team API via VITE_API_BASE_URL (config-only, R6).
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Unit/integration tests live in src/. The Playwright e2e specs (e2e/) run under a
    // real browser via `npm run e2e`, not Vitest.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
