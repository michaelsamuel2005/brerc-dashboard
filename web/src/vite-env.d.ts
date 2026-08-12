/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_A11Y_TEST_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
