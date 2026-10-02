// Decides whether the browser starts the MSW mock layer.
//
// Two rules, in order, and the order is the point:
//
//  1. A production build NEVER mocks. This is checked first and nothing can
//     override it, so no environment variable, misconfiguration or stray
//     `.env` file can put a fake data layer in front of real BRERC data.
//  2. Within a development build only, `VITE_USE_REAL_API=1` turns the mock
//     off, so a developer can point `npm run dev` at a locally-running API
//     instead of the fixtures. See docs/RUN_LOCALLY.md.
//
// Lives in its own module rather than inline in main.tsx so the rule above can
// be tested — main.tsx mounts React as a side effect and cannot be imported by
// a unit test.

/** The subset of `import.meta.env` this decision reads. */
export interface MockingEnv {
  readonly DEV?: boolean;
  readonly VITE_USE_REAL_API?: string;
}

/** Values that mean "skip the mock and call the real API". Anything else keeps mocks on. */
const OPT_OUT = new Set(["1", "true"]);

export function shouldEnableMocking(env: MockingEnv): boolean {
  // Rule 1 — fail closed towards "no mock layer" outside development.
  // `!== true` rather than `=== false`: an absent or non-boolean DEV is not a
  // development build either.
  if (env.DEV !== true) return false;
  // Rule 2 — development default is mocked; opt out explicitly.
  return !OPT_OUT.has((env.VITE_USE_REAL_API ?? "").trim().toLowerCase());
}
