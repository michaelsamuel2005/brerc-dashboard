/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_A11Y_TEST_MODE?: string;
  // Dev only: "1" runs `npm run dev` against a locally-running API instead of
  // the MSW mock. Ignored by production builds — see src/app/mocking.ts.
  readonly VITE_USE_REAL_API?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
