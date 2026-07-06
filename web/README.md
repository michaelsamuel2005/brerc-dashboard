# `web/` — public dashboard front end (Michael's area)

React + TypeScript + Vite, with **MapLibre GL JS** (via `react-map-gl/maplibre`)
for the map and **React Aria Components** for accessible UI primitives.

## You can build all of this with NO backend

The data layer ships with **realistic mock data**, so the whole UI runs on its own.
You don't need PostgreSQL, Docker, or a running API to build and see your work.

```bash
npm install
npm run dev            # http://localhost:5173  — runs on MOCK data by default
```

- `src/mocks/` holds the fake data (`fixtures.ts`) and a mock API (`mockApi.ts`).
- `src/api/client.ts` exposes `api` — it returns the mock data by default, and the
  **real** API when you set `VITE_USE_MOCKS=false` (once a teammate's backend
  exists). Your components import `api`; they don't change when you switch.
- For the map while mocking: use `CELLS_GEOJSON` from `src/mocks/fixtures.ts` as a
  MapLibre **GeoJSON source**, then switch to Martin vector tiles
  (`tileUrlTemplate`) when the tile server is ready.

## What to build (your part)

The **components** and the **App wiring** are stubs for you to implement — that's
the learning. Follow **[`../BUILD_PLAN.md`](../BUILD_PLAN.md)** (the front-end
phase). The contracts (`src/types.ts`), the client, and the mock data are already
done so you can focus on the UI and accessibility.

## Scripts

| Script | Purpose |
|--------|---------|
| `npm run dev` | Vite dev server (mock data). |
| `npm run build` | Type-check + production build. |
| `npm run typecheck` | Strict TypeScript, no emit. |
| `npm run lint` | ESLint incl. `jsx-a11y` accessibility rules. |
| `npm run test` | Vitest component + **axe** accessibility tests. |
| `npm run format` | Prettier. |

## Accessibility (WCAG 2.2 AA — a legal requirement)

Keep the data **table** as the accessible equivalent of the map; semantic
landmarks, a skip link, visible focus, ≥ 4.5:1 contrast, no colour-only encoding;
lint with `jsx-a11y` and test with `jest-axe`. See `../docs/ACCESSIBILITY.md`.
