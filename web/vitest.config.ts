import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

// Component + accessibility (axe) tests run in jsdom. The WebGL map is not
// rendered here (jsdom has no WebGL); accessibility is asserted on the DOM
// components that surround the map — which is exactly what WCAG requires, since
// online maps are exempt but the information they convey must be accessible.
export default mergeConfig(
  viteConfig({ mode: 'test', command: 'serve' }),
  defineConfig({
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./vitest.setup.ts'],
      css: false,
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }),
);
