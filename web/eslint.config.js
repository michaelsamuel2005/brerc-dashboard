import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import tseslint from 'typescript-eslint';

// Accessibility linting (jsx-a11y) is a first-class gate here: WCAG 2.2 AA is a
// legal requirement, so a11y lint errors fail the build in CI like any other.
export default tseslint.config(
  { ignores: ['dist', 'coverage'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'jsx-a11y': jsxA11y,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // CLAUDE.md: no `any` without an explicit, reasoned comment.
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
  {
    // Test files may use vitest globals.
    files: ['**/*.test.{ts,tsx}', 'vitest.setup.ts'],
    languageOptions: { globals: { ...globals.node } },
  },
);
