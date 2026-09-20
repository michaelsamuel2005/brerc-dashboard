# Accessibility candidate evidence — 20 September 2026

**Decision:** automated candidate checks passed; final manual release approval remains
blocked.

## Tested source

- Branch: `michael/production-linux-handover`
- Commit: `7b26846fc4d0d2fb2e03e8f40cb3a0934b17bae0`
- Working tree when evidence was collected: clean
- Data mode: controlled synthetic `msw-mock`

## Results

- TypeScript typecheck: passed.
- ESLint: passed.
- Vitest unit/contract/accessibility tests: passed.
- Browser serialization: 8 passed.
- Playwright browser suite: 96 passed, 1 intentional emulated-touch skip.
- Evidence scopes: 90.
- Scopes with `automatedGatesPassed=true`: 90.
- Scopes with `releaseGatesPassed=true`: 0.
- Manual gate observations: 810 `not-assessed` entries (nine gates across 90 scopes).
- Human-decision findings awaiting a scoped reviewer disposition: 5,597 across the 90
  evidence scopes (162 distinct descriptions repeated across browser/state/viewport
  combinations). These are review candidates, not 5,597 independently confirmed defects.

Projects exercised:

- Chromium: 320 × 640, 360 × 640, 390 × 844, 768 × 1024, 844 × 390,
  1440 × 900 and 1920 × 1080;
- Firefox: 320 × 640; and
- WebKit: 390 × 844.

## Honest interpretation

This is strong regression evidence for the candidate's deterministic accessibility
checks and controlled UI states. It is not the final deployed-build review, a human
screen-reader/touch assessment, an independent audit or approval of the accessibility
statement.

The final run must follow
[ACCESSIBILITY_RELEASE_EVIDENCE.md](ACCESSIBILITY_RELEASE_EVIDENCE.md) after the exact
protected-`main` build is deployed. Named reviewers must complete all nine manual
gates, close and independently retest defects, and obtain BRERC service-owner approval
of the statement for the actual hosting arrangement.
