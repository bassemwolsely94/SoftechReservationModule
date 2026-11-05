// ESLint 9 flat config (test plan R8): `npm run lint`.
//
// Errors are real defects (undefined names, broken hook order, raw HTML injection, duplicate
// keys, unreachable code). Rules that the existing code breaks in large numbers are WARNINGS for
// now, each with its reason; their counts are in docs/security/2026-11-05-r8-frontend-report.md
// and they come down batch by batch. A rule is never switched off to go green.
import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'

export default [
  { ignores: ['public/**', 'dist/**', 'node_modules/**', 'playwright-report/**', 'test-results/**', 'e2e/.auth/**'] },

  js.configs.recommended,
  react.configs.flat.recommended,
  react.configs.flat['jsx-runtime'],

  {
    files: ['**/*.{js,jsx,mjs,cjs}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser },
    },
    settings: { react: { version: 'detect' } },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      // Hooks called conditionally or out of order break React state: always an error.
      'react-hooks/rules-of-hooks': 'error',
      // Missing effect dependencies. Warn: many effects deliberately run once or on one key,
      // and "fixing" each by adding every dependency can create request loops. Reviewed per screen.
      'react-hooks/exhaustive-deps': 'warn',

      // Raw HTML injection (XSS) — the test plan requires this on.
      'react/no-danger': 'error',
      // The app has no PropTypes; components are typed by usage. Not a defect.
      'react/prop-types': 'off',
      // Arabic UI text is full of quotes and apostrophes inside JSX; escaping them is noise.
      'react/no-unescaped-entities': 'off',
      // Older pages declare inline components without a name; harmless at runtime.
      'react/display-name': 'warn',

      // Unused imports / variables: warn (dead code, not a runtime bug). `_x` marks a deliberate skip.
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none',
                                   ignoreRestSiblings: true }],
      // `catch {}` / `catch { /* … */ }` blocks that intentionally swallow a storage or network error.
      'no-empty': ['warn', { allowEmptyCatch: true }],
    },
  },

  // Node-side files: build scripts, configs, Playwright.
  {
    files: ['scripts/**', '*.config.{js,mjs}', 'e2e/**'],
    languageOptions: { globals: { ...globals.node } },
  },
  // Unit tests run under Vitest + jsdom.
  {
    files: ['src/**/*.test.{js,jsx}'],
    languageOptions: { globals: { ...globals.node } },
  },
]
