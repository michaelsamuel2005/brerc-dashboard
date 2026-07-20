# BRERC Public Dashboard — Front-end (`web/`)

Public, accessible, map-based explorer for BRERC species records.
**React + TypeScript (strict) + Vite.** This is the public front-end (Michael's scope);
the API is team-owned, and this app develops against an **MSW mock** of the agreed
contract, so it runs with **no backend**.

## Quick start
```bash
cd web
rm -rf node_modules dist *.tsbuildinfo   # clear stale scaffold artefacts
npm install
npm run dev          # runs against the MSW mock — no backend needed
npm run typecheck    # strict TS, no `any`
npm run test:run     # unit + C2 contract + accessibility tests
```
> Dev mocking uses a service worker: run `npx msw init public/ --save` once so
> `npm run dev` can serve the mock in the browser. (Tests use the Node mock and need nothing.)

## What's here — Phase 0 (foundations) + Phase 1 (contract-first spine)
- **`lib/api/`** — the ONLY network layer: per-endpoint **Zod schemas** (contract source of
  truth), typed `client`, `endpoints`, and **TanStack Query** hooks. Nothing else calls `fetch`.
- **`lib/api/contract.test.ts`** — the **C2 gate**: fails if any forbidden field
  (`Recorder1/BLISS/Eastings/Northings/Comments/sensitivity`) could enter a parsed payload,
  or if a record's `gridRef` is finer than its stated `precisionMetres`.
- **`test/msw/`** — mock implementing the API contract + PII/sensitivity-free fixtures
  (incl. a generalised, unlabelled sensitive-taxon example blended into the ordinary grid).
- **`types/`** — PII-free domain types, **inferred from Zod** so they can't drift.
- **`lib/geo/`** — grid-ref precision/label helpers (display-only; never upsamples precision).
- **`config/`** — Zod-validated env (`VITE_*` only; dev→prod is a base-URL swap, no code change).
- **`app/` + `features/`** — accessible shell (skip link, landmarks, per-feature error boundaries)
  and a first slice (overview, species list, R5 records table) rendering live from the mock.

## C2 (data safety) in one line
Sensitive-location generalisation is enforced **server-side**; the client's job is to make it
**impossible** for precise coords/PII to appear. Strict Zod `.strict()` schemas + the contract
test are the client-side net (the server contract is the fix — see assumptions A3/A4).

## API endpoints (all mocked here)
`/api/summary` · `/api/species` · `/api/species/{id}` · `/api/distribution/cells` ·
`/api/records` · `/api/meta/provenance` · `/api/health`

## Next steps
- **Finish P0:** React Aria primitives, design-token depth, ESLint + `jsx-a11y`,
  CI + forbidden-field build guard, ADRs.
- **P2:** the MapLibre distribution map (`react-map-gl/maplibre`) + colour-safe legend,
  reusing this exact data layer — plus the `/api/distribution/tiles` MVT path.
