import { describe, expect, it } from "vitest";
import { shouldEnableMocking } from "./mocking";

describe("shouldEnableMocking", () => {
  it("mocks by default in development, so the app runs with no backend", () => {
    expect(shouldEnableMocking({ DEV: true })).toBe(true);
    expect(shouldEnableMocking({ DEV: true, VITE_USE_REAL_API: "" })).toBe(true);
  });

  it("skips the mock in development when the developer opts out", () => {
    for (const value of ["1", "true", "TRUE", " 1 "]) {
      expect(shouldEnableMocking({ DEV: true, VITE_USE_REAL_API: value })).toBe(false);
    }
  });

  it("keeps mocking for values that are not a clear opt-out", () => {
    for (const value of ["0", "false", "no", "yes", "real"]) {
      expect(shouldEnableMocking({ DEV: true, VITE_USE_REAL_API: value })).toBe(true);
    }
  });

  it("never mocks outside development, whatever the opt-out flag says", () => {
    // The safety rule: no environment value can reintroduce a fake data layer
    // in front of real BRERC data in a production build.
    for (const flag of [undefined, "", "0", "1", "true", "false"]) {
      expect(shouldEnableMocking({ DEV: false, VITE_USE_REAL_API: flag })).toBe(false);
      expect(shouldEnableMocking({ VITE_USE_REAL_API: flag })).toBe(false);
    }
  });
});
