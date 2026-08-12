# BRERC accessibility maintainer runbook

Updated 26 July 2026

The accessibility tooling is integrated into `web/`; this is a runbook, not a
copy-and-paste integration guide.

## What is wired into the application

- `DistributionMap` exposes its MapLibre instance, canonical polygons and selectable
  layer IDs only when both Vite development mode and `VITE_A11Y_TEST_MODE=true` are
  present.
- Production builds contain no accessibility-adapter globals.
- The map and grid table use the same API collection and the same client-derived
  OS-grid polygons.
- The map has four 44-pixel directional controls as a non-dragging alternative.
- Grid-square and year buttons are real 44-pixel DOM controls.
- Focusable table overflow regions are labelled for keyboard users and marked as
  non-pointer targets for the geometry collector.
- Loading, empty and error scenarios are served by development-only MSW behavior selected
  through the `brerc-a11y-scenario` cookie.

The automated fixture data is synthetic. The footer deliberately labels it illustrative.

## Local verification

Use Node 20 or newer:

```bash
cd web
npm ci
npm run typecheck
npm run lint
npm run guard
npm run test:run
npm run build
```

Install all supported Playwright engines once, then run the browser contracts:

```bash
npm run e2e:install
npm run e2e:serialization
npm run e2e
```

`e2e:serialization` is deliberately separate and first. It catches functions that work
in Node but fail after Playwright serializes them into a page.

The main matrix currently discovers 91 tests: 10 functional app checks and 81
state/camera matrix checks across Chromium, WebKit and Firefox projects.

On a restricted macOS sandbox, a Playwright shell browser may be denied its Mach-port
registration before any test body starts. That is an environment failure, not a passing
or failing dashboard assertion. Run the matrix in GitHub Actions or an unrestricted
local terminal and retain its artifacts.

## Configuration contract

Executable selectors, states, layers and cameras live in:

- `web/e2e/a11y.config.ts`
- `web/e2e/playwright.viewports.ts`

Pure camera constants live in `web/src/features/map/mapConstants.ts` so Playwright’s
Node process does not import a module containing `import.meta.env`.

The selected layer is `cells-fill`. If the app changes a selector, state, layer or camera
boundary, update this contract and its tests in the same change. State-entry assertions
must fail before stale geometry is accepted as evidence.

## Evidence locations

Main matrix output:

```text
web/test-results/a11y-evidence/
web/test-results/
web/playwright-report/
```

GitHub Actions uploads these directories with `if: always()`. Do not commit generated
evidence from arbitrary dirty runs as release proof. Retain evidence for the exact commit
being approved.

## Reviewer resolutions

The ledger is `web/e2e/a11y-resolutions.json`. It starts empty and has a strict runtime
schema. A resolution requires:

- finding ID and current fingerprint;
- exact project, viewport, state, camera and data-mode scope;
- permitted outcome;
- reviewer, real date and rationale.

Only `needs-human-decision` findings can be dismissed. A deterministic WCAG,
project-requirement or data-quality finding remains blocking until code/data changes
remove it. Do not copy a resolution between scopes unless the evidence and decision
genuinely apply and each entry validates.

## Manual results

Manual results are stored in `web/e2e/a11y-manual-results.json`. The nine required IDs
are:

```text
screenReader
realDeviceTouch
textResize200
browserZoom400
contrastSweep
keyboardAndFocus
pointerCancellation
statusAnnouncements
orientation
```

Each supplied result needs:

```json
{
  "outcome": "pass",
  "reviewer": "Full name",
  "date": "2026-07-26",
  "environment": "Device, OS, browser and assistive technology",
  "evidence": "Artifact or test-note reference"
}
```

Missing entries leave release approval false without making the automated CI verdict
false.

## Production adapter check

After `npm run build`, verify the generated JavaScript does not contain:

```text
__brercMap
__brercCanonicalCells
__brercSelectableLayers
__brercA11yBridgeReady
```

The normal build runs without `VITE_A11Y_TEST_MODE`; Vite/Rollup must remove the
test-only branch.

## Focused mutation evidence

The authoritative entry point is:

```bash
npm run a11y:mutate
```

It:

1. hashes the current mutation inputs;
2. copies the current `web/` snapshot to a system temporary directory;
3. installs exact lockfile dependencies in that copy;
4. requires a token-matched sentinel before the inner runner can start;
5. type-checks and runs the full unit suite before, during and after mutation;
6. writes JSON and Markdown atomically from the same result;
7. verifies the original inputs are unchanged;
8. copies reports to `web/test-results/a11y-mutation/`.

For a harness-only smoke test:

```bash
python3 mutation/run_disposable.py --max-mutants 1
```

A limited run deliberately publishes no score. The full result is described as a
focused operator score, not a general TypeScript mutation score.

## CI

`.github/workflows/ci.yml` runs ordinary gates plus:

- all three browser installations;
- serialization tests;
- the full main matrix;
- always-uploaded diagnostics.

`.github/workflows/a11y-mutation.yml` runs the longer mutation sweep weekly and on
manual dispatch. It is evidence-strengthening work, not a per-commit substitute for unit
or browser tests.

## Before release

1. Run ordinary and browser gates against the release commit.
2. Inspect every automated finding and artifact.
3. Fix deterministic findings; do not waive them.
4. Complete reviewer resolutions for genuine human-decision findings.
5. Complete and retain all nine manual results.
6. Confirm `releaseGatesPassed` for every required evidence scope.
7. Obtain the client’s accessibility/legal decision on map-exemption wording.
8. Only then make a conformance or release statement.
