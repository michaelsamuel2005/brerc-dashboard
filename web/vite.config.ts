/// <reference types="vitest/config" />
import process from "node:process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The public front-end build. dev/test run entirely against the MSW mock (A11);
// production points at the team API via VITE_API_BASE_URL (config-only, R6).

// Where a locally-running API lives, for the dev-server and preview-server
// proxies below. Deliberately NOT a `VITE_` name: `VITE_`-prefixed variables are
// inlined into the client bundle, and this value must never leave the developer's
// machine. Nothing here affects the production build — Vite ships neither the
// dev server nor the preview server.
const LOCAL_API = process.env.BRERC_LOCAL_API ?? "http://127.0.0.1:8000";

// In production the app and the API are served from one origin behind a reverse
// proxy (D-001), so the client calls the relative path `/api`. These proxies
// reproduce that same-origin shape locally: `npm run preview` — and `npm run dev`
// with VITE_USE_REAL_API=1 — forward `/api` to the local API, so the browser makes
// no cross-origin request and no CORS allowance is needed to look at real data.
// See docs/RUN_LOCALLY.md.
const localApiProxy = {
  "/api": {
    target: LOCAL_API,
    changeOrigin: false,
  },
} as const;

export default defineConfig({
  cacheDir: ".vite-cache",
  plugins: [react()],
  server: { proxy: localApiProxy },
  preview: { proxy: localApiProxy },
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
