# BRERC Public Dashboard — Front-end (`web/`)

Public, accessible, map-based explorer for BRERC species records.
**React + TypeScript (strict) + Vite.** This is the public front-end (Michael's scope);
the API is team-owned, and this app develops against an **MSW mock** of the agreed
contract, so it runs with **no backend**.

## Quick start
```bash
cd web
npm install
npm run dev          # runs against the MSW mock — no backend needed
npm run typecheck    # strict TS, no `any`
npm run lint         # ESLint + typescript-eslint + jsx-a11y
npm run guard        # C2 forbidden-field / secret source guard
npm run test:run     # unit + C2 contract + accessibility (jest-axe) tests
npm run build        # production build
```
> Dev mocking uses a service worker (`public/mockServiceWorker.js`, already committed).
> Browser end-to-end + axe (`npm run e2e`) needs a real browser: `npm run e2e:install` once, then `npm run e2e`.

## What's here — Phase 0 + Phase 1 + Phase 2
**P0 (foundations):** strict TS, accessible shell (skip link, landmarks, per-feature error
boundaries), design tokens (AA), ESLint + `jsx-a11y`, the `guard` script, and a CI workflow
(`.github/workflows/ci.yml`).

**P1 (contract-first spine):**
- **`lib/api/`** — the ONLY network layer: per-endpoint **Zod schemas** (contract source of
  truth), typed `client`, `endpoints`, **TanStack Query** hooks. Nothing else calls `fetch`.
- **`test/msw/`** — mock implementing the contract; PII/sensitivity-free fixtures. The
  distribution + records endpoints honour the `?species=` filter.
- **`types/`** — PII-free domain types, **inferred from Zod** so they can't drift.
- **`lib/geo/`** — grid-ref precision/label helpers (display-only; never upsamples precision).

**P2 (one-species vertical slice — Slow-worm):**
- **`features/map/DistributionMap.tsx`** — the distribution map on **`react-map-gl/maplibre`**,
  honest grid cells at their true 1 km extent (never pins), colour-safe legend, ≥44 px controls,
  a secure React-children popup (no `innerHTML`), and a graceful error surface.
- **`features/species/CellSummaryTable.tsx`** — the map's **accessible equivalent**: the SAME
  `CellCollection`, as a table (grid square, resolution, records, verified).
- **`features/species/RecordsTable.tsx`** — a labelled SAMPLE of individual records.
- **`features/species/SpeciesPanel.tsx`** + **`components/AttributedImage.tsx`** — species info
  with a licence/attribution-safe image slot and a graceful "photograph pending" fallback.
- Every panel is scoped by the same `speciesId`.

## C2 (data safety)
Sensitive-location generalisation is enforced **server-side**; the client makes it **impossible**
for precise coords/PII to appear. The client net is now a **runtime gate**, not just a fixture test:
- `.strict()` Zod schemas reject any unexpected key (`Recorder1/BLISS/Eastings/Northings/Comments/sensitivity`).
- Each record's grid reference must resolve to **exactly** its `precisionMetres`, and everything
  must be **≥ 100 m** (the public floor) — enforced in the schema, on every parsed response.
- URLs must be **https** (no `javascript:`/`data:` attribution links).
- `contract.test.ts` + `npm run guard` back this in CI.

## Verification gates
`typecheck`, `lint`, `guard`, `test:run` (unit + contract + jest-axe), and `build` all pass and
run in CI. **Browser checks (WebGL render, tiles, keyboard, responsive) run via Playwright + axe
(`npm run e2e`) and are the remaining gate — run them in a browser before sign-off.**

## API endpoints (all mocked here)
`/api/summary` · `/api/species` · `/api/species/{id}` · `/api/distribution/cells` ·
`/api/records` · `/api/meta/provenance` · `/api/health`

## Next steps (P3)
Deepen the map: all species (not one), MVT tiles (`/api/distribution/tiles`), full keyboard
operability of cells with the table kept in sync, and the wire-level C2 re-proof against the real API.
