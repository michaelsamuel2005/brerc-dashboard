# `web/` — public dashboard front end

React + TypeScript + Vite, with **MapLibre GL JS** (via `react-map-gl/maplibre`)
for the map and **React Aria Components** for accessible UI primitives. This is
the browser half of the primary deliverable.

## Run it

Against the full stack (recommended): `make up` from the repository root serves
the built app behind the proxy at <http://localhost:8080/>.

Standalone dev server (hot reload) against a running API + Martin:

```bash
cd web
npm install
npm run dev            # http://localhost:5173  (proxies /api and /tiles — see vite.config.ts)
```

Point the dev proxy at non-default upstreams with `VITE_DEV_API_TARGET` and
`VITE_DEV_TILES_TARGET`.

## Scripts

| Script | Purpose |
|--------|---------|
| `npm run dev` | Vite dev server with hot reload. |
| `npm run build` | Type-check (`tsc -b`) then build to `dist/`. |
| `npm run typecheck` | Strict TypeScript check, no emit. |
| `npm run lint` | ESLint, including `jsx-a11y` accessibility rules. |
| `npm run test` | Vitest component + **axe** accessibility tests. |
| `npm run format` | Prettier. |

## How it stays accessible (WCAG 2.2 AA)

- The **data table** (`components/DataTable.tsx`) is the accessible equivalent of
  the map and renders the *same* generalised, counted cells — so a screen-reader
  user gets the same information without the (exempt) map.
- Semantic landmarks (`header`, `main`, `aside`), a skip link, an explicit
  `lang`, a matching `<title>`, visible focus, ≥ 4.5:1 text contrast, and no
  colour-only encoding (the legend uses text + size; sensitive cells also carry a
  text badge).
- `react-aria-components` provides correct combobox ARIA and keyboard handling.
- Accessibility is linted (`jsx-a11y`) and tested (`jest-axe`) in CI.

## Data contract

Types in `src/types.ts` mirror `api/app/models.py`. If you change one, change the
other in the same pull request. The front end only ever reads generalised,
PII-free data — it talks to the API and to Martin, both of which read the
`public_occurrences` gate.
