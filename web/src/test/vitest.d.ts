import 'vitest';

// Type the jest-axe matcher (registered in test/setup.ts) for Vitest's expect,
// so `expect(await axe(...)).toHaveNoViolations()` type-checks.
interface CustomMatchers<R = unknown> {
  toHaveNoViolations: () => R;
}

declare module 'vitest' {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  interface Assertion<T = any> extends CustomMatchers<T> {}
  interface AsymmetricMatchersContaining extends CustomMatchers {}
}
