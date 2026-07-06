# Build plan

This is a **mono-repo** for the whole team. It has two tracks:

- **Front end (`web/`) — Michael's area.** Detailed below. You build it against
  **mock data**, so you need no backend and no PostgreSQL.
- **Backend (`db/`, `api/`, `tiles/`, `proxy/`, `internal-web/`) — a teammate's
  area.** Summarised at the bottom so you know how the pieces connect; not yours
  to build.

## How to use this plan (front end)

Go top to bottom. Each step names the files, the acceptance check, and a pointer
to reference material (the **Learning Guide** and a worked **Answer Key**, kept
separately — use when stuck). Build against mock data the whole way; flip to the
real API at the very end when a teammate's backend is ready.

## The rules that apply to you

1. **WCAG 2.2 AA is a legal requirement.** The interface must be keyboard-operable,
   high-contrast, and screen-reader friendly, and the **data table** must be an
   accessible equivalent of the map. This is the front end's headline
   responsibility — own it.
2. The map shows **generalised** data only (the backend blurs sensitive locations).
   You never handle precise data; the mock data is already generalised, like the
   real thing.

---

## Phase 0 — Setup

- [ ] `cd web && npm install`
- [ ] `npm run dev` → open <http://localhost:5173>. You'll see the skeleton with
      placeholder panels, running on **mock data** (no backend needed).
- [ ] Skim `web/src/mocks/fixtures.ts` (the fake data) and `web/src/api/client.ts`
      (your `api` object). Your components will import `api` and `types`.

## Phase F1 — The data table (start here; it's the backbone)

> Files: `web/src/components/DataTable.tsx` (+ its test). Data: `api.cells(filters)`.
> Reference: Learning Guide Module 5 & 6 · Answer Key `web/src/components/DataTable.tsx`.
> Acceptance: the table shows rows of mock cells; `npm run test` + `npm run typecheck` green.

- [ ] Build a real HTML `<table>` with a caption and `scope`d headers: species,
      group, grid square, resolution, records, years, sensitive.
- [ ] Show the **sensitive** flag as a text badge (not colour alone).
- [ ] It's the accessible equivalent of the map — keep it correct and readable.

## Phase F2 — Search, filters, summary

> Files: `SpeciesSearch.tsx` (React Aria ComboBox), `Filters.tsx`, `SummaryBar.tsx`.
> Data: `api.searchSpecies(q)`, `api.filters()`, `api.summary()`.
> Reference: Learning Guide Module 5. Acceptance: choosing a species/filter changes the table.

- [ ] `SummaryBar` — headline totals from `api.summary()`.
- [ ] `FiltersPanel` — taxon-group `<select>` + year inputs (native elements are
      accessible for free); options from `api.filters()`.
- [ ] `SpeciesSearch` — accessible autocomplete (React Aria `ComboBox`) calling
      `api.searchSpecies`.

## Phase F3 — Species info panel

> Files: `SpeciesInfoPanel.tsx`. Data: `api.speciesInfo(name)`.
> Reference: Learning Guide Module 5. Acceptance: shows a photo + licence for Robin,
> and a **placeholder** for Otter (no reusable image).

- [ ] Show the image only when `has_image` is true; always show licence +
      attribution; otherwise a named placeholder. Meaningful `alt` text.

## Phase F4 — The map

> Files: `MapView.tsx`, `MapLegend.tsx`. Reference: Learning Guide Modules 3 & 5 ·
> Answer Key `web/src/components/MapView.tsx`. Acceptance: the map shows the mock
> cells; the legend explains size + the sensitive marker in words.

- [ ] While mocking, add a MapLibre **GeoJSON source** from `CELLS_GEOJSON`
      (`web/src/mocks/fixtures.ts`) and a circle layer sized by `occurrence_count`.
- [ ] Encode by **size** (not colour alone); give sensitive cells a distinct outline.
- [ ] Later (Phase F7) swap the GeoJSON source for Martin vector tiles via
      `tileUrlTemplate` — the rest of the component stays the same.

## Phase F5 — Wire it together (App)

> Files: `web/src/App.tsx`. Reference: Learning Guide Module 5 · Answer Key `web/src/App.tsx`.
> Acceptance: picking a species/filter updates the map AND the table together.

- [ ] Hold `filters` (species, group, years) and `selected` species in `App`; pass
      them to the children so the map and table always agree.

## Phase F6 — Accessibility pass + tests

> Files: `web/src/components/a11y.test.tsx`, `DataTable.test.tsx`.
> Reference: Learning Guide Module 6. Acceptance: `npm run test` (axe) + `npm run lint` green;
> keyboard + screen-reader passes done.

- [ ] Replace the `it.todo` stubs with real component + **axe** tests (zero
      violations).
- [ ] Do a keyboard-only walk-through, and a VoiceOver pass (⌘+F5) on the table.

## Phase F7 — Connect to the real backend (when it's ready)

- [ ] When a teammate's API + tiles are live, set `VITE_USE_MOCKS=false` in `.env`
      and point `VITE_API_BASE` / `VITE_TILES_BASE` at them. Your components don't
      change — only the data source does.

---

## Backend track (a teammate — for your awareness only)

Not your work, but this is how the halves meet. The backend builds, in order: the
`occurrences` table → the **`public_occurrences` gate** (blurs sensitive
locations) → the Martin tile function → the read-only FastAPI endpoints your `api`
client will call. The endpoint shapes it must return are exactly your
`web/src/types.ts` contracts, so if a teammate matches those, `VITE_USE_MOCKS=false`
just works. The full backend steps live in the stubs' `TODO` headers and the
reference material.

## Definition of done (front end)

`npm run typecheck && npm run lint && npm run test && npm run build` all green; no
axe violations; keyboard + screen-reader checked; the map and table stay in sync.
See `CONTRIBUTING.md`.
