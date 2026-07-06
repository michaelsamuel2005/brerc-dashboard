# Build plan

The ordered, step-by-step plan to turn this foundation into the working dashboard.
Everything the plumbing needs is already here; you implement the logic where the
`TODO` stubs are.

## How to use this plan

- **Go top to bottom.** The order follows how data flows (database → gate → tiles →
  API → screen), and each phase depends on the one before it. Building the safety
  (the gate) *before* anything that serves data is the whole point — don't reorder.
- **One file at a time.** Every stub has a `TODO` header telling you what to build,
  the acceptance test, and where to look. Implement it, run the acceptance test,
  commit, move on.
- **Reference material** (kept outside this repo): the **Answer Key** (a full
  implementation) and the **Learning Guide** (modules that teach each part). Each
  stub names the exact file/module. Try first; peek when stuck.
- **Keep it green.** After each step run the relevant `make` check. Open a pull
  request per phase (or per file) so CI runs and a teammate reviews.

## The two rules (never break these)

1. Sensitive locations are generalised **server-side, fail-closed** — every public
   read goes through `public_occurrences`, never the precise table.
2. The interface targets **WCAG 2.2 AA**, with an accessible table equivalent of
   the map.

## Suggested team split

You own the dashboard + PostgreSQL, so drive Phases 1–4. Good parallel tracks once
Phase 2 is done: one person on the front end (Phase 5), one on the internal tool
(Phase 6), one on docs + accessibility statement + deployment (Phase 7). Agree who
owns what in your kickoff and put it in `CODEOWNERS`.

---

## Phase 0 — Setup (everyone, day one)

- [ ] `cp .env.example .env` and set local passwords (never commit `.env`).
- [ ] `cd web && npm install && npm run dev` — confirm the **skeleton runs** (you'll
      see placeholder panels).
- [ ] `make up` then `make db-migrate` — confirm the stack starts and `0001`
      (PostGIS) applies.
- [ ] Push a branch and open a PR — confirm **CI is green** on the empty skeleton.
      (It is, by design: stub tests pass; you'll replace them with real ones.)

## Phase 1 — Database foundation

> Reference: Learning Guide Module 2. Acceptance: `make db-migrate` clean.

- [ ] `db/migrations/0002_core_occurrences.sql` — the precise `occurrences` table
      (geometry in `EPSG:27700`, grid ref + precision, dates, `recorder1`, `bliss`)
      and the `public_config` dials. Mark guessed columns `[assumed]`.
- [ ] `scripts/gridref.py` — parse OS grid refs → easting/northing + precision;
      `EPSG:27700`→`4326` with `always_xy=True`; generalise to a cell centre.
      Acceptance: write a couple of asserts in `scripts/test_gridref.py` and run
      `cd scripts && python -m pytest`.
- [ ] `scripts/seed_synthetic.py` + `db/seed/seed_synthetic.sql` — generate FAKE
      West-of-England records so the map has something to draw. Acceptance:
      `make db-seed` loads rows.

## Phase 2 — THE GATE (the heart — take your time)

> Reference: Learning Guide Module 2 (read section 4 slowly). Acceptance:
> `make gate-test` passes.

- [ ] `db/migrations/0003_sensitive_species.sql` — the control-list table.
- [ ] `db/seed/sensitive_species_demo.sql` — a few SYNTHETIC sensitive taxa (some at
      10 km, one "review", one "blocked").
- [ ] `db/migrations/0004_public_occurrences_view.sql` — `generalise_point`,
      `en_to_gridref`, and the `public_occurrences` view. Blur to the cell centre;
      pick the **coarsest** of {baseline, source precision, sensitive requirement};
      drop PII + precise columns; omit blocked/no-geometry rows.
- [ ] `db/migrations/0006_roles.sql` — the read-only `brerc_readonly` role: deny the
      precise table, grant only the view + tile function.
- [ ] `db/tests/test_generalisation_gate.sql` — replace the placeholder with the real
      assertions (no PII/precise columns; nothing finer than baseline; sensitive at
      their tier; blocked absent; role can't read `occurrences`).
- [ ] Run `make gate-test` until it's green. **This is your most important milestone.**

## Phase 3 — Tiles (the map data)

> Reference: Learning Guide Module 3. Acceptance: `GET /tiles/public_occurrences`
> returns TileJSON.

- [ ] `db/migrations/0005_tile_functions.sql` — `public_occurrences_mvt(z,x,y,params)`
      reading the gate only, aggregating per (species, cell) with a count, honouring
      filters. Then `docker compose restart martin`.
- [ ] `db/migrations/0007_indexes.sql` — add the spatial + btree indexes (do this once
      queries work, to keep them fast).

## Phase 4 — The API

> Reference: Learning Guide Module 4. Acceptance: endpoints return data in
> `/api/docs`; `cd api && pytest` green.

- [ ] `api/app/models.py` — the response models (keep in step with `web/src/types.ts`).
- [ ] `api/app/routers/species.py` — `/species/search`, `/species/filters`.
- [ ] `api/app/routers/occurrences.py` — `/occurrences/summary` and `/occurrences/cells`
      (the accessible table data). Parameterised SQL, row caps.
- [ ] `api/app/services/licensing.py` + `species_info.py` +
      `api/app/routers/species_info.py` — the cached, fail-closed species-info proxy.
- [ ] Replace the skipped test stubs (`test_licensing.py`, `test_species_info.py`,
      `test_generalisation_gate.py`) with real tests.

## Phase 5 — The front end

> Reference: Learning Guide Modules 5 & 6. Acceptance: `cd web && npm run typecheck &&
> npm run test && npm run build` green; keyboard + axe pass.

- [ ] `web/src/types.ts` — the data contracts (mirror `api/app/models.py`).
- [ ] `web/src/api/client.ts` — the typed API client + `tileUrlTemplate`.
- [ ] Build the components, wiring real props + state as you go:
      `SummaryBar`, `SpeciesSearch` (React Aria), `Filters`, `SpeciesInfoPanel`,
      `MapView` (react-map-gl/maplibre), `MapLegend`, and **`DataTable`** (the
      accessible map equivalent).
- [ ] `web/src/App.tsx` — replace the skeleton wiring with real `filters` + `selected`
      state driving both the map and the table.
- [ ] Replace the `it.todo` test stubs with real component + **axe** tests. Do a
      keyboard-only pass and a screen-reader pass (Module 6).

## Phase 6 — Internal data-quality dashboard (secondary)

> Reference: Learning Guide Module 7. Acceptance: `make dq-test` passes;
> `make internal-up` serves it on localhost only.

- [ ] `db/internal/0010_data_quality_views.sql` — the DQ + content views.
- [ ] `db/internal/0011_internal_role.sql` — the internal read-only role.
- [ ] `db/seed/internal_dq_demo.sql` + `db/tests/test_data_quality.sql` — demo
      anomalies + the real test.
- [ ] `api/app/routers/internal.py` — the gated `/internal/*` endpoints (+ real
      `api/tests/test_internal.py`).
- [ ] `internal-web/index.html` — the single-file staff UI.

## Phase 7 — Polish & ship

> Reference: Learning Guide Module 8. Acceptance: the pre-publication checklist in
> `docs/HANDOVER.md`.

- [ ] Fill in the doc skeletons in `docs/` (architecture, data model, sensitive
      species, deployment, handover, internal) as the code settles.
- [ ] Complete + publish the accessibility statement (`docs/ACCESSIBILITY_STATEMENT.md`).
- [ ] Confirm the three BRERC open items (embedding, the real sensitive-species list
      loaded into the DB, production DB ownership).
- [ ] Do the dev→production switch (change `PUBLIC_DATABASE_URL` only) and run the
      pre-publication checklist.

---

## Definition of done for any change

Lint + typecheck + unit tests pass; the gate test passes; no new axe violations;
docs updated if behaviour changed; the PR explains the reasoning for the next
maintainer (who may be non-technical BRERC staff). See `CONTRIBUTING.md`.
