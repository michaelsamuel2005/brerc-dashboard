# BRERC Public Dashboard — Front-end (`web/`)

Public, accessible, map-based explorer for BRERC species records.
**React + TypeScript (strict) + Vite + MapLibre** — the stack in `Architecture_Decision.md`.
This is the public front-end; the API is team-owned, and the app develops against an **MSW
mock** of the agreed contract, so it runs with **no backend**.

## Quick start

See **[../docs/RUN_LOCALLY.md](../docs/RUN_LOCALLY.md)** for viewing the app
against the real API as well as the mock.

```bash
cd web
npm install
npm run dev          # runs against the MSW mock — no backend needed
                     # VITE_USE_REAL_API=1 npm run dev  → a local API instead
npm run typecheck    # strict TS, no `any`
npm run lint         # ESLint + typescript-eslint + jsx-a11y
npm run guard        # C2 forbidden-field / secret source guard
npm run guard:bundle # after build: fails if the MSW mock reached the public bundle
npm run test:run     # unit + C2 contract + accessibility (jest-axe)
npm run build        # production build
npm run e2e:install && npm run e2e   # browser: WebGL, keyboard, bidirectional sync, axe
```

## What's here — P0–P3 (slice 1)
**P0/P1:** strict TS, accessible shell, design tokens (AA), ESLint + `jsx-a11y`, the `guard`
script, CI (`.github/workflows/ci.yml`); the `lib/api` Zod contract (single source of truth),
typed client + TanStack Query hooks, MSW mock, PII-free fixtures.

**P2/P3 (one species, Slow-worm) — map-first:**
- **`features/map/DistributionMap.tsx`** — react-map-gl/maplibre. Cell polygons are **derived
  client-side from validated grid IDs** (`lib/geo/osgb.ts`), so server geometry is never
  trusted. A two-layer light/dark halo marks the selected cell.
- **`features/species/CellSummaryTable.tsx`** — the map's **accessible equivalent** and its
  keyboard control surface: per-row buttons select/highlight a square.
- **`features/species/SelectedCellCard.tsx`** — one authoritative selected-cell readout beside
  the map (`aria-live`); selection is shared map⇄table⇄card. No popup, no auto-scroll.
- **`RecordsTable`** (a policy-gated published-records view) + **`SpeciesPanel`** (credited
  descriptions or an honest unavailable state) + **`AttributedImage`** (licence/attribution-
  safe slot with a graceful fallback).

## C2 (data safety)
Sensitive-location generalisation is enforced **server-side**. The client provides a second,
structural runtime gate; it does not claim to detect personal information hidden inside an
otherwise allowed text value:
- `.strict()` Zod rejects any unexpected key (`Recorder1`, `RecordKey`, `unique_no`, `BLISS`,
  `easting(s)`, `northing(s)`, `Comments`, `sensitive` or `sensitivity`).
- Public free-text values must be constructed server-side; raw `Source` text is replaced by
  the controlled `BRERC` organisational label before the browser contract.
- A record's grid ref must resolve to **exactly** its `precisionMetres`; a distribution cell's
  `cellId` must too — and the map derives geometry from that ID, so a precise polygon cannot be
  mislabelled as a coarse cell. Everything is **≥ 100 m** (the public floor).
- `verified` mapping tests **reject before accept** (a negative verdict is never read as accepted).
- URLs must be **https**. `contract.test.ts` + `npm run guard` enforce this in CI.

## Verification gates
The isolated publication-contract staging run passes strict `typecheck` and **462/462** unit,
contract and accessibility tests. Repository CI additionally runs `lint`, `guard`, `build` and
browser checks —
WebGL render, keyboard, bidirectional map⇄table selection, and a "map click does not scroll the
page" assertion — run via **Playwright + axe (`npm run e2e`)** at desktop and mobile.

## API endpoints (all mocked here)
`/api/summary` · `/api/species` · `/api/species/{id}` · `/api/distribution/cells`
(returns `{verificationAvailable, cells:[{cellId, precisionMetres, recordCount,
verifiedCount?}]}` — IDs, not geometry; `verifiedCount` is required only when verification is
available) ·
`/api/records` · `/api/meta/provenance` · `/api/health`

## Next
P3 slice 2 — MVT/PMTiles tiles + viewport fetch (once the backend tile endpoint is agreed with
Victor) and a records-by-year chart (Recharts). Then P4 — multi-species browsing.
