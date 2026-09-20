# Accessibility release evidence and manual review

This is the release procedure for the BRERC public dashboard. It separates evidence
that software can collect from observations that must be made and signed by named
people using real browsers, devices and assistive technology.

Passing automated tests is necessary but is not an accessibility approval. W3C notes
that tools cannot determine accessibility on their own, and GOV.UK guidance calls for
automated, manual and assistive-technology testing:

- <https://www.w3.org/WAI/test-evaluate/tools/selecting/>
- <https://www.gov.uk/service-manual/helping-people-to-use-your-service/testing-for-accessibility>
- <https://www.gov.uk/service-manual/technology/testing-with-assistive-technologies>

## Current verified position — 20 September 2026

The pre-release candidate at
`7b26846fc4d0d2fb2e03e8f40cb3a0934b17bae0` was clean when tested. Local
verification produced:

- 8/8 browser-serialization checks passing;
- 96 Playwright checks passing and one intentional emulated-touch skip;
- Chromium coverage at seven viewports, Firefox at 320 × 640 and WebKit at
  390 × 844;
- 90 JSON evidence records, all with `automatedGatesPassed=true`; and
- zero records with `releaseGatesPassed=true` because all nine manual gates are
  honestly `not-assessed`.

Those 90 records use controlled `msw-mock` scenarios. They prove the automated UI
states and diagnostics, not the deployed API, final content, hosting arrangement or
human usability. The separate live acceptance uses the mocks-disabled production
bundle and real synthetic PostGIS/FastAPI stack. It is configured to run in Chromium,
Firefox and WebKit.

**The final accessibility review is not complete.** There is no frozen deployed
protected-`main` build and no named human attestation yet. Never copy the candidate
result into the final record or describe the candidate as an accessibility approval.

## Completion rule

Release accessibility evidence is complete only when all of the following refer to
the same immutable deployment:

1. protected-`main` commit, CI run, production build, runtime configuration, data
   release, media manifest and tile/privacy configuration are frozen by digest;
2. the automated unit, axe, state-matrix and mocks-disabled three-engine browser runs
   pass on that commit;
3. every current human-decision finding in `web/e2e/a11y-resolutions.json` has a named,
   scoped and still-valid disposition;
4. named reviewers complete and evidence all nine manual gates;
5. every confirmed defect is fixed and independently retested on the replacement
   build; and
6. the accessibility/content owner and BRERC service owner approve the accessibility
   statement for the actual public URL and hosting arrangement.

Any later change to UI code, CSS, ARIA, public content, media, runtime configuration,
tile configuration or hosting can invalidate affected evidence and requires a scoped
retest. A blocking WCAG A/AA defect is a failure, not a “pass with caveat”.

## 1. Freeze the exact review target

Use a clean checkout of the deployed protected-`main` commit. Do not use a feature
branch, a localhost-only build or a different rebuild of the same source. Download and
unpack the `public-web-<sha>-<run>-<attempt>` artifact from a fully green CI run. Deploy
that retained artifact unchanged, and do not substitute a new local `npm run build`
output. Copy the artifact into the controlled long-term release archive before CI's
90-day retention expires.

```bash
git fetch origin main
git switch --detach <deployed-full-main-sha>
git status --short
```

Set the following values in the review shell. They are deliberately not stored in the
repository:

- `A11Y_EXPECTED_SHA` — deployed 40-character commit SHA;
- `A11Y_REPOSITORY_ID` — public host/path identifier without credentials;
- `A11Y_DEPLOYED_URL` — final HTTPS review URL;
- `A11Y_CI_RUN_URL` — CI run for that exact SHA;
- `A11Y_HOSTING_ARRANGEMENT` — public domain/embedding and same-origin API arrangement;
- `A11Y_PUBLIC_DATA_RELEASE_ID` — active public release identifier;
- `A11Y_BUILD_ARTIFACT_DIR` — unpacked exact CI artifact that was deployed;
- `A11Y_RUNTIME_CONFIG_FILE` — reviewed runtime configuration file;
- `A11Y_MEDIA_MANIFEST_FILE` — approved media manifest;
- `A11Y_TILE_PRIVACY_CONFIG_FILE` — approved tile/style/privacy decision; and
- optionally `A11Y_OUTPUT_FILE` — controlled output location.

Then create the immutable target manifest:

```bash
cd web
npm run a11y:freeze
```

The command refuses a dirty tree, an SHA mismatch, a non-HTTPS target or missing
inputs. It also verifies the artifact's required entry point and map worker and rejects
an artifact containing the browser mock layer. It records hashes, not configuration
contents or Git remote credentials, rejects URLs containing credentials or fragments,
and will not overwrite an existing manifest. Store the manifest with the review
evidence, retain the `manifest: sha256:...` value it prints, and confirm that the
recorded artifact digest matches the deployed files.

## 2. Run and retain automated evidence

From `web/`:

```bash
npm ci
npm run e2e:install
npm run typecheck
npm run lint
npm run guard
npm run test:run
npm run build
npm run guard:bundle
npm run e2e:all
```

Retain `test-results/a11y-evidence`, Playwright diagnostics and the CI URL. The normal
accessibility matrix uses deterministic synthetic MSW scenarios so loading, empty,
error and selected states can be reproduced. It must be complemented by the
mocks-disabled production-build test against the deployed/synthetic acceptance stack:

```bash
LIVE_BASE_URL=https://<review-host> \
  npx --no-install playwright test --config playwright.live.config.ts
```

The live run must report `live-chromium`, `live-firefox` and `live-webkit`. Its API
requests must reach the same-origin live API; only the external CARTO raster request is
replaced with a stable transparent test tile.

## 3. Manual review scope

Test each unique template and route in the actual deployed routing arrangement:

- Overview;
- Explore map;
- species directory;
- representative species detail with media, without media and with long content;
- Records/accessible grid-cell table;
- About the data;
- Accessibility statement;
- Privacy and Settings; and
- not-found routing.

Exercise at least these states: default; navigation/drawer open; disclosure open;
light and dark theme; selected species, cell and year; loading/updating; no results;
API failure and retry; tile failure; media failure; and browser back/forward.

For every observation record: test ID, gate, WCAG reference, exact URL, state,
preconditions, steps, expected and actual result, reviewer, timestamp and timezone,
hardware, physical/emulated status, OS, browser, assistive technology, input method,
viewport, device-pixel ratio, zoom/text scale, orientation, theme, evidence filenames
and SHA-256 values.

### `keyboardAndFocus`

- `KB-01`: first Tab exposes the skip link; activation visibly focuses main content.
- `KB-02`: navigate every route and browser history in a logical order.
- `KB-03`: open/close the drawer and disclosures; Escape works and focus returns.
- `KB-04`: operate search, filters, pagination, theme and settings without a pointer.
- `KB-05`: pan/zoom the map without dragging and use the equivalent cell table.
- `KB-06`: select/clear cells and years; map, table and card remain coherent.
- `KB-07`: focus remains visible and unobscured at 100%, 200% and 400%.

Fail on a trap, unreachable control, focus loss, illogical order, pointer-only action or
obscured focus.

### `screenReader`

Use VoiceOver/Safari and at least one of NVDA/Firefox, JAWS/Chrome or Edge, or
TalkBack/Chrome. GOV.UK's current combinations are the baseline, not an exhaustive
list.

- `SR-01`: document title, language, landmarks, headings and current page.
- `SR-02`: drawer/dialog name, state, reading order and focus return.
- `SR-03`: species search results and count.
- `SR-04`: table caption, headers, rows and grid-cell precision/count.
- `SR-05`: selected/cleared cell and selected/reset year.
- `SR-06`: map and chart have complete textual/table equivalents.
- `SR-07`: media alternatives, credits, licence and no-media fallback.
- `SR-08`: loading, empty, failure and retry are understandable without duplicate
  canvas noise or focus theft.

Retain a transcript or controlled recording reference. Code inspection or an ARIA
snapshot cannot replace this observation.

### `textResize200`

Use Firefox text-only zoom at 200%, then apply WCAG text-spacing overrides. Check every
template, control, legend, card, table and statement for lost, overlapping, clipped or
truncated information. Confirm the map/table relationship remains understandable.

### `browserZoom400`

Use real 400% browser zoom from a 1280-CSS-pixel desktop viewport, producing the
320-CSS-pixel reflow case. Complete every critical task. Fail unexpected root
horizontal scrolling, lost content, overlapping controls, changed reading order or
obscured focus. A clearly labelled complex-data/map region may scroll internally only
when its accessible alternative remains available.

### `contrastSweep`

Measure actual rendered and composited foreground/background combinations in light,
dark and forced-colour modes. Include normal/large text, focus, control boundaries,
hover, selected, disabled and error states, map legend, translucent cells and chart
graphics. Record the tool and unrounded readings; check that colour is never the only
way information is communicated.

### `realDeviceTouch`

Use at least one physical iOS/Safari device and one physical Android/Chrome device;
include a phone and tablet across the round. Test drawer, search/filters, disclosures,
links, map/page gesture coexistence, map controls, cell/year selection, table scrolling
and the on-screen keyboard. Confirm effective targets meet the project's 44 × 44
CSS-pixel rule and do not cause accidental activation.

### `pointerCancellation`

For each control type, press inside, move outside and release. The action must not
commit on pointer-down. Confirm map dragging does not select a cell, touch cancellation
works, toggles activate once and safely reversible actions can be undone.

### `statusAnnouncements`

With desktop and mobile screen readers trigger loading/completion, search result
counts, selected/cleared cell, selected/reset year, API failure/retry and empty results.
Confirm each appropriate update is announced once, is current and understandable, and
does not steal focus.

### `orientation`

On physical phone and tablet, repeat critical flows in portrait and landscape,
including with the drawer open, an active filter and the on-screen keyboard visible.
Fail an orientation lock, missing content, unusable controls, root horizontal scroll or
unexplained loss of selection/focus.

## 4. Record results and defects

The canonical release schema contains the nine gate IDs above. Map equivalence,
tables/charts, reduced motion, magnification/speech and content accuracy remain
mandatory observations within those gate cases, but they are not separate top-level
attestation IDs. This document supersedes earlier standalone drafts that required
fourteen incompatible top-level gate names.

Only after a reviewer actually completes a gate, add one entry to a controlled external
copy of `web/e2e/a11y-manual-results.json`:

```json
{
  "gate": "keyboardAndFocus",
  "outcome": "pass",
  "reviewer": "Reviewer's real name",
  "date": "YYYY-MM-DD",
  "environment": "Device, OS, browser, assistive technology and versions",
  "evidence": "Controlled evidence record IDs and a concise observed-result summary",
  "commitSha": "the reviewed 40-character commit SHA",
  "releaseManifestSha256": "sha256:the 64-character digest of the frozen target manifest",
  "deployedUrl": "https://the-reviewed-public-or-acceptance-host/"
}
```

Never enter a placeholder reviewer or infer a pass from automation. All nine gates are
required for this dashboard, so the parser accepts only `pass` or `fail`; it rejects
`not-applicable`, malformed targets and duplicate entries. The evidence builder also
fails an attestation if the browser run is dirty or if its commit, deployed URL or
manifest digest differs from the frozen target. Do not edit the tracked empty template
after freezing: that would change or dirty the source being approved. Keep the completed
record in the controlled evidence store and pass its absolute path at runtime. A
confirmed problem must include severity, reproducible steps, owner, defect URL, fix
SHA/build and independent retest reviewer/date/outcome. Preserve the failed evidence as
well as its replacement.

After the nine entries and reviewer-resolution ledger are complete, rerun
the matrix against the clean frozen checkout:

```bash
export A11Y_MANUAL_RESULTS_FILE=/controlled/evidence/a11y-manual-results.json
export A11Y_RELEASE_MANIFEST_SHA256=sha256:<frozen-manifest-digest>
export A11Y_DEPLOYED_URL=https://<exact-reviewed-host>/
npm run e2e
```

The three target values must exactly match every attestation. The generated JSON must
report both `automatedGatesPassed=true` and `releaseGatesPassed=true` for every scope.

## 5. Approve the accessibility statement

The statement must not be published with `[BRERC to confirm: ...]` placeholders or a
draft banner. The accessibility/content owner and BRERC service owner must approve,
against the same frozen digest:

- the final public URL and hosting/embedding scope covered by the statement;
- preparation and review dates;
- accurate compliance status and every known non-compliance;
- the manual/assistive-technology test outcome and any independent audit status;
- an accessible contact email/postal route and response-time commitment; and
- the enforcement wording and ownership for ongoing review.

Record names, roles, UTC timestamps, decision and statement version/URL. If the hosting
arrangement or reviewed build changes, reassess the statement before activation.
