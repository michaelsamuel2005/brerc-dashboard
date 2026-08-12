// Flat ESLint config (ESLint 9). Non-type-checked rules — fast, no tsconfig project needed.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import globals from "globals";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "coverage/**",
      "playwright-report/**",
      "test-results/**",
      "node_modules/**",
      ".vite-cache/**",
      "screenshots/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2022, globals: { ...globals.browser } },
    plugins: { "react-hooks": reactHooks, "jsx-a11y": jsxA11y },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.configs.recommended.rules,
      // A scrollable region made focusable (role=group + tabIndex) is a WCAG-positive
      // pattern (axe "scrollable-region-focusable"), so permit tabIndex on group.
      "jsx-a11y/no-noninteractive-tabindex": ["warn", { tags: [], roles: ["group"], allowExpressionValues: true }],
    },
  },
  {
    files: ["**/*.test.{ts,tsx}", "src/test/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["e2e/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
  {
    files: ["**/*.{mjs,js,cjs}", "*.config.{ts,js,mjs}"],
    languageOptions: { globals: { ...globals.node } },
  },
);
