# CLAUDE.md — repository conventions

Guidance for any contributor (human or AI assistant) working in this repository.
It encodes the decisions that are already settled so they are not re-litigated.
If this file conflicts with the engagement's source-of-truth documents, **those
documents win**; reflect the change here in the same pull request.

## What this repository is

The **public-facing BRERC dashboard** and its **PostgreSQL integration** — the
primary deliverable of the 180DC × BRERC engagement. Interactive
species-distribution maps + species info/images, served live from PostGIS, built
to WCAG 2.2 AA.

## Settled architecture (do not re-open without a superseding decision)

- **Data:** PostgreSQL 16 + PostGIS. One precise, private `occurrences` table; a
  `sensitive_species` table; and the **`public_occurrences` view** — the single
  source every public read path uses.
- **Tiles:** **Martin** serves MVT vector tiles from a PostGIS **function
  source** that reads the generalised view only.
- **API:** thin **read-only FastAPI** service (search, filters, aggregated
  counts, cached species info).
- **Front end:** **React + TypeScript + Vite** with **MapLibre GL JS** and
  accessible UI primitives (React Aria).
- **Embedding:** same-origin **reverse proxy** (Caddy) under the council domain.
- **Fallback:** Plotly Dash, reusing the same PostGIS + Martin layer, if the
  front-end build outruns the clock (see `docs/DECISIONS.md`, D-006). Not built
  unless invoked.

Full rationale: `docs/ARCHITECTURE.md`. Decision log: `docs/DECISIONS.md`.

## Hard gates (enforced in code + tests — never weaken silently)

1. **Sensitive-species generalisation is server-side and fail-closed.** Snap
   coordinates with `ST_SnapToGrid` in **`EPSG:27700`** metres in
   `public_occurrences`; drop `Recorder1` and any PII; default-generalise
   anything not positively confirmed safe. Public tiles/API read the view, never
   `occurrences`. `db/tests/` + `api/tests/test_generalisation_gate.py` assert it.
2. **WCAG 2.2 AA across the whole interface** — keyboard, visible focus, 4.5:1
   text contrast, correct ARIA names/roles, no colour-only encoding; an
   accessible data-table equivalent for essential map information.
3. **Read-only, parameterised, bounded.** Read-only DB role; GET-only API;
   parameterised SQL; statement timeouts + row caps on user-facing queries.
4. **Image licensing fail-closed.** Only display a species image with a
   confirmed reusable licence + attribution; otherwise show a named placeholder.

## Canonical names (use exactly — consistency is graded)

`BRERC` · `LERC` · `NBN / NBN Atlas` · `180DC` · `EPSG:27700` (British National
Grid / OSGB36, metres) · `EPSG:4326` (WGS84 lat/lon) · monad = 1 km · tetrad =
2 km · hectad = 10 km · `Recorder1` (recorder name field, PII) · `BLISS` (source
dataset field) · `public_occurrences` (the generalised view) · Martin · MapLibre
GL JS · FastAPI · MVT / vector tile · "generalisation" (coordinate blurring — not
"anonymisation"). Team, always alphabetical: Aman, Athul, Michael, Ting Ting,
Victor.

## Coding conventions

- **Comment for a non-developer maintainer.** BRERC staff may maintain this;
  explain *why*, not just *what*, especially around CRS maths and the gate.
- **Python:** 3.11+, type hints, `ruff` (lint+format), `mypy`. Async FastAPI +
  `asyncpg`. No ORM for the read paths — explicit, parameterised SQL that is easy
  to audit. Never build SQL by string concatenation of user input.
- **TypeScript/React:** strict mode on; functional components + hooks; no `any`
  without a comment; ESLint with `jsx-a11y`. Keep components small; keep the
  map's data-table equivalent in sync with what the map shows.
- **SQL:** one migration per file, ordered and idempotent where practical;
  `sqlfluff` (postgres dialect). CRS is explicit in every spatial operation.
- **Tests:** add tests with new logic. The generalisation gate and the grid-ref
  maths are the highest-value tests — keep them green.
- **Secrets & data:** never hard-code either; never commit `data/` or `.env`.

## Definition of done for a change

Lint + typecheck + unit tests pass; the gate test passes; no new axe violations;
docs updated if behaviour changed; PR description explains the reasoning for the
next maintainer.
