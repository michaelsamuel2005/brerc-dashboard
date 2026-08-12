# BRERC dashboard mobile accessibility test protocol

Version 5.0 · 26 July 2026

## 1. Purpose and status

This protocol defines repeatable accessibility evidence for the BRERC public dashboard,
with particular attention to the map, touch targets, narrow screens and equivalent data
tables.

It is a test protocol, not a declaration of WCAG conformance. Automated evidence can
identify many defects, but release approval additionally requires named manual checks
with assistive technology and physical devices. Legal ownership of any public-sector map
exemption also remains with Bristol City Council/BRERC; the project does not infer it from
test results.

The application uses synthetic Slow-worm fixtures during automated testing. Those
fixtures test behavior, consistency and privacy boundaries; they do not prove the
accuracy or accessibility of a future live API.

## 2. Evidence architecture

The evidence path has four distinct layers:

1. Browser collectors measure plain geometry and diagnostics.
2. Node-side classifiers make deterministic or review-required findings.
3. A reviewer ledger records decisions only for genuine human-decision findings.
4. Nine named manual gates determine whether a release can be approved.

The final JSON therefore exposes two verdicts:

- `automatedGatesPassed`: suitable for CI.
- `releaseGatesPassed`: true only when automated, reviewer-ledger and manual gates pass.

A green CI run is not, by itself, release approval or a WCAG conformance claim.

## 3. Automated scope

The executable suite covers:

- DOM pointer-target geometry for WCAG 2.2 SC 2.5.8 and BRERC’s 44 CSS-pixel rule.
- WebGL map-cell geometry derived from the canonical grid polygons used by the app.
- Spacing interactions between DOM controls and rendered map cells.
- Root reflow, unexpected horizontal overflow and clipped table-cell content.
- HTML and SVG text-spacing diagnostics for SC 1.4.12.
- A functional non-dragging map-pan alternative for SC 2.5.7.
- Deterministic loading, empty, error, disclosure, selected-cell and selected-year states.
- Axe rules available in the installed version for WCAG 2 A/AA, 2.1 A/AA and 2.2 AA
  tags.
- Browser-serialization tests proving every collector can actually cross the
  Playwright `page.evaluate` boundary.

Axe does not provide the target-size decision in the installed toolchain. The custom
geometry suite is the SC 2.5.8 gate.

The SVG chart bars are presentational. Year filtering is performed through the
equivalent 44-pixel buttons in the chart’s data table.

## 4. Browser and state matrix

Chromium is exercised at:

| ID | Viewport | Purpose |
|---|---:|---|
| V1 | 320×640 | normative narrow reflow width |
| V2 | 360×640 | compact Android-style viewport |
| V3 | 390×844 | common iOS logical size |
| V4 | 768×1024 | tablet portrait |
| V5 | 844×390 | short landscape viewport |
| V6 | 1440×900 | desktop |
| V7 | 1920×1080 | wide desktop |

The matrix also includes WebKit at 390×844 and Firefox at 320×640. Emulated WebKit is
not a substitute for physical iOS Safari.

Each matrix project exercises:

- default;
- attribution expanded;
- chart table expanded;
- grid cell selected;
- year selected;
- loading;
- empty;
- error.

Loading, empty and error are entered through a test-only scenario cookie consumed by the
application’s own MSW handlers. Each state is asserted before evidence is collected.
The generic Playwright-route stubs from earlier protocol versions are no longer used.

Map-applicable states run the initial camera. Separate tests run the supported minimum
and maximum zoom. Every scheduled camera fixes bearing and pitch to zero and records the
centre, bounds, canvas position, viewport, DPR, style and sources.

## 5. Target-size method

The DOM collector includes actual links, buttons, form controls, summaries, custom
controls and explicitly marked pointer targets. It excludes:

- zero-area or CSS-hidden controls;
- controls within a closed `details` element, except its visible `summary`;
- keyboard-scrollable regions explicitly marked as non-pointer targets.

For each target the collector records the raw, unrounded rectangle. A target is
undersized if either dimension is below 24 CSS pixels. BRERC’s stricter project finding
is raised below 44 CSS pixels.

The WCAG spacing exception is calculated, never accepted from a developer tag. The
24-pixel circle around an undersized target must clear every other target rectangle and
every interactive map-cell obstacle. An undersized neighbor additionally participates
in the circle-to-circle test. Exact tangency is not treated as overlap.

Rounded, transformed, clipped, non-rectangular or overlapping regions require review;
their bounding boxes cannot automatically prove a pass. Developer assertions such as
same-action groups are recorded but never trusted as evidence without a current reviewer
decision.

Map cells are measured from client-derived OS-grid polygons, not arbitrary API geometry.
`queryRenderedFeatures` confirms current interactivity only. A missing adapter, skipped
cell, unknown rendered ID or missing cell ID is evidence failure/inconclusive, never a
pass.

## 6. Reflow and text spacing

At every viewport, the suite records:

- document client and scroll widths;
- root horizontal scrolling;
- root/body overflow suppression;
- unexpected elements outside the viewport;
- content intentionally inside horizontal table scroll regions;
- clipped table cells.

Map canvases are handled under the complex two-dimensional-content exception, but
essential map information remains available through the grid-square table.

The DOM text-spacing diagnostic applies:

- line height 1.5;
- letter spacing 0.12 em;
- word spacing 0.16 em;
- paragraph spacing 2 em.

SVG text is tested separately because CSS line height does not apply to SVG text.
Screenshots are retained because bounding boxes cannot prove that labels do not collide.

## 7. Evidence and reviewer ledger

Every evidence record includes:

- project, browser, engine, viewport, state and camera;
- installed dependency versions from the lockfile;
- branch, commit and tri-state tree cleanliness;
- hashes of the configuration, fixtures, ledger, manual results and lockfile;
- automated diagnostics, findings, gates and blockers.

A ledger entry is scoped by:

```json
{
  "project": "a11y-chromium-V1-320x640",
  "viewport": "320x640",
  "state": "default",
  "camera": "initial-z12",
  "dataMode": "msw-mock"
}
```

Ledger JSON is runtime-validated as a whole. Dates must be real ISO calendar dates.
Unknown, duplicate, stale or out-of-vocabulary entries invalidate the ledger.
Deterministic WCAG, project and data-quality findings cannot be dismissed. The ledger is
a reviewer-attested repository record with stale-evidence fingerprints; it is not a
cryptographic signature.

## 8. Manual release gates

Each gate must record `pass`, `fail` or genuinely justified `not-applicable`, plus the
reviewer, date, environment and evidence reference.

1. `screenReader` — VoiceOver/Safari and at least one of NVDA/Firefox or
   TalkBack/Chrome: landmarks, names, focus, selection announcements and table reading.
2. `realDeviceTouch` — physical phone/tablet: map controls, cell/year selection,
   disclosures and scroll regions without accidental activation.
3. `textResize200` — browser text-only resize at 200%, including map/table relationship.
4. `browserZoom400` — desktop browser zoom at 400% and equivalent 320 CSS-pixel reflow.
5. `contrastSweep` — computed foreground/background contrast, focus indicators,
   map legend and selected states, including opacity/compositing.
6. `keyboardAndFocus` — logical order, skip link, visible focus, no trap and no obscured
   focused control.
7. `pointerCancellation` — no essential action on pointer-down; cancellation/undo
   behavior verified.
8. `statusAnnouncements` — loading, error, selection and filtering changes announced
   appropriately without disruptive focus movement.
9. `orientation` — portrait and landscape operation on physical devices.

Store results in `web/e2e/a11y-manual-results.json`. Empty results correctly keep
`releaseGatesPassed` false.

## 9. Commands

From `web/`:

```bash
npm ci
npm run typecheck
npm run lint
npm run guard
npm run test:run
npm run build

npm run e2e:install
npm run e2e:serialization
npm run e2e
```

CI installs Chromium, Firefox and WebKit, runs serialization before the main matrix, and
uploads evidence, screenshots, ARIA snapshots, traces and reports even when a test fails.

The focused mutation sweep is separate from per-commit release gates:

```bash
npm run a11y:mutate
```

It runs only in a disposable copy and publishes no score when the run is partial,
timed-out or inconclusive.

## 10. Limitations and release rule

Automated checks do not replace physical-device touch testing, assistive-technology
testing, cognitive/usability review, live-data validation, or legal review. The
network-independent test basemap proves the BRERC data layer without making third-party
tile availability part of the gate.

Release approval requires:

- all ordinary code gates;
- serialization and full browser matrix success;
- no unresolved deterministic finding;
- a current ledger for every genuine human-decision finding;
- all nine manual gates;
- retained evidence for the exact release commit.

Until those conditions are met, report the implementation and test status accurately but
do not claim WCAG 2.2 AA conformance.
