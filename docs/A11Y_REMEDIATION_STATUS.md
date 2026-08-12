# BRERC accessibility remediation status

As of 26 July 2026

## Decision

The supplied v2 bundle was not safe to accept unchanged. Its core geometry work was
useful, but the executable configuration, ledger scope, evidence verdict, deterministic
states, CI and mutation claims contained stop-ship defects.

Those defects have now been corrected in the integrated implementation described below.
This is not yet a WCAG conformance sign-off: the formal browser matrix must complete in
an unrestricted runner, reviewer resolutions remain empty, and all manual gates remain
unassessed.

## Current verification record

| Area | Current status |
|---|---|
| Strict application + accessibility TypeScript | Green in live worktree |
| ESLint | Green in live worktree |
| Forbidden-field/privacy guard | Green in live worktree |
| Unit/integration tests | 356/356 passing across 21 files |
| Production build | Green in live worktree |
| Playwright discovery | 91 main tests discovered |
| Serialization discovery | 8 tests discovered |
| Formal Playwright execution in this Codex sandbox | Blocked before test bodies by macOS Mach-port denial |
| In-app responsive smoke pass | 320, 360, 390, 768, 844 landscape, 1440 and 1920 checked |
| Reviewer resolution ledger | Empty |
| Nine manual release gates | Empty/unassessed |
| Disposable mutation smoke | Green in live worktree; 1/257 candidates processed safely |
| Focused mutation score | Not measured; partial smoke correctly published no percentage |
| Release approval | Blocked pending browser CI + reviewer/manual evidence |

The ordinary gates above were re-run after the verified files were copied into the live
repository.

## Remediations completed

### Executable test architecture

- The actual E2E spec imports one application contract for selectors, states, layers and
  cameras.
- Vite-dependent map styling is separated from pure camera constants so Playwright can
  discover tests in Node.
- Every browser collector has a real-browser serialization contract.
- The map test adapter is compile-time guarded and excluded from production.
- Loading, empty and error use endpoint-correct MSW scenarios and are asserted before
  evidence collection.
- The suite distinguishes states where a map is intentionally not applicable.

### Geometry and map behavior

- DOM spacing checks test every neighboring target rectangle and undersized-target
  circles.
- Map cells independently report WCAG 24-pixel and BRERC 44-pixel thresholds.
- Canonical polygons are derived from validated OS grid references; API geometry is not
  trusted.
- Map coordinates are translated into viewport coordinates before cross-surface spacing
  checks.
- Missing cell IDs, skipped cells and rendered/canonical mismatches cannot silently pass.
- The map has minimum/initial/maximum camera evidence and four functional directional
  controls.
- Collapsed disclosure contents are no longer measured as visible targets.
- Keyboard-scrollable table regions are no longer misclassified as pointer activation
  targets.
- The skip link no longer creates a false root-overflow finding while unfocused.

### Evidence and governance

- `automatedGatesPassed` is separate from `releaseGatesPassed`.
- Root overflow, overflow suppression, clipping, state entry, pan behavior, text spacing
  and axe results are part of the automated evidence.
- Ledger scope includes project, viewport, state, camera and data mode.
- Entire ledger files are runtime-validated; impossible dates, unknown scope values,
  duplicate entries and invalid outcomes are rejected.
- Deterministic defects cannot be dismissed through the reviewer ledger.
- Nine named, structured manual gates are required for release.
- “Signed” language was replaced with accurate reviewer-attested terminology.

### CI and mutation safety

- CI installs Chromium, Firefox and WebKit.
- Serialization runs before the main browser matrix.
- Evidence, screenshots, ARIA snapshots, reports and failure diagnostics are uploaded.
- The old in-place mutation script is not used.
- The supported mutation command works in a disposable copy, verifies original hashes,
  uses strict TypeScript, includes `manualGates.ts`, distinguishes invalid/timeouts/
  inconclusive results, and derives JSON/Markdown from one result.
- Partial or inconclusive mutation runs publish no score.

### Application accessibility

- The map is first in DOM and visual order at narrow widths.
- Map, grid table and selected-cell card share one authoritative selection.
- Selection does not force-scroll the page.
- Chart bars are presentational; equivalent year buttons are at least 44 CSS pixels.
- Table regions are keyboard-scrollable and labelled.
- Reduced-motion preference is respected.
- All displayed data remains explicitly described as illustrative/synthetic.

## Items still required before release approval

1. Run `npm run e2e:serialization` and `npm run e2e` in GitHub Actions or another
   unrestricted environment and inspect every artifact.
2. Resolve any actual browser geometry, reflow, axe or state failure in code.
3. Review genuine human-decision findings and commit current, scoped ledger entries.
4. Complete all nine manual gates on physical devices and named assistive technologies.
5. Run the full disposable focused mutation sweep if a score is required; review every
   survivor rather than calling it equivalent automatically.
6. Obtain and retain the client/legal owner’s conclusion on public-sector map-exemption
   wording.

Until then, the accurate statement is: the accessibility architecture and automated
test design are integrated and substantially remediated, but final browser/manual
evidence and release approval are still pending.
