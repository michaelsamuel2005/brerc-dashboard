import "vitest";
import "@testing-library/jest-dom/vitest";

interface CustomMatchers<R = unknown> {
  toHaveNoViolations(): R;
}
declare module "vitest" {
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type
  interface Assertion<T = unknown> extends CustomMatchers<T> {}
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type
  interface AsymmetricMatchersContaining extends CustomMatchers {}
}
