# BRERC Dashboard

<!-- Badges: replace `OWNER` with your GitHub username/org at publish time (the publish script does this). -->
[![CI](https://github.com/OWNER/brerc-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/brerc-dashboard/actions/workflows/ci.yml)
[![CodeQL](https://github.com/OWNER/brerc-dashboard/actions/workflows/codeql.yml/badge.svg)](https://github.com/OWNER/brerc-dashboard/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Accessibility: WCAG 2.2 AA](https://img.shields.io/badge/accessibility-WCAG%202.2%20AA-1b5e20.svg)](docs/ACCESSIBILITY.md)
![Stack: PostGIS · Martin · FastAPI · React](https://img.shields.io/badge/stack-PostGIS%20%C2%B7%20Martin%20%C2%B7%20FastAPI%20%C2%B7%20React-informational.svg)

An accessible, public, interactive dashboard of biodiversity records for the
**Bristol Regional Environmental Records Centre (BRERC)** — the Local
Environmental Records Centre (LERC) for the West of England (Bristol, Bath &
North East Somerset, North Somerset, South Gloucestershire).

It presents **interactive species-distribution maps** with **species information
and images**, served live from BRERC's **PostgreSQL/PostGIS** database. Precise
locations of sensitive species are **generalised in the database, before they
ever leave the server**, and the whole interface targets **WCAG 2.2 AA**, a legal
requirement for a public-sector body.

> ### 🏗️ This repository is a foundation we are building out as a team.
> The **plumbing is done** (structure, config, Docker, CI, docs); the **core
> logic is stubbed** with `TODO`s. Follow **[`BUILD_PLAN.md`](BUILD_PLAN.md)** to
> implement it, step by step. Every stub points to the module and reference
> material that shows you how.

180 Degrees Consulting Bristol × BRERC · kick-off 1 Jul 2026 · showcase 17 Aug 2026.

---

## The two rules that shape everything

These are **hard gates**, not preferences — enforced in code and covered by tests
(see [`docs/DATA_GOVERNANCE.md`](docs/DATA_GOVERNANCE.md)). Respect them from your
first commit:

1. **Sensitive-species locations are generalised server-side, fail-closed.** The
   `public_occurrences` view blurs coordinates to a coarse grid (in `EPSG:27700`
   metres) and drops recorder PII **before** any tile or API response is produced.
   Every public read path selects from this view — never from the precise
   `occurrences` table.
2. **The whole interface targets WCAG 2.2 AA.** Essential map information also has
   an **accessible non-map equivalent** (a filterable data table), and the site
   publishes a gov.uk-model accessibility statement.

## What's in the box

```
PostgreSQL 16 + PostGIS
  └─ public_occurrences   VIEW: generalises coordinates, drops PII, FAILS CLOSED
        ├─ Martin  ───────────► vector tiles (MVT) ─────────────┐
        └─ FastAPI (read-only)► JSON: search, filters, counts,  ├─► React + Vite + TS
             cached species info (iNat→GBIF→Wikipedia + licence)┘    MapLibre GL JS + React Aria
   All behind a same-origin Caddy reverse proxy for embedding in BRERC's website.
```

| Path | What it is | State |
|------|------------|-------|
| `db/` | PostGIS schema, the **`public_occurrences` gate**, the Martin tile function, roles, and the gate test. | 🔨 build |
| `api/` | Read-only **FastAPI**: search, filters, aggregated counts (the accessible table), cached species-info proxy. | 🔨 build |
| `tiles/` | **Martin** vector-tile server config (reads the gate only). | ✅ config done |
| `web/` | **React + TypeScript + Vite** front end with **MapLibre GL JS** + accessible UI. | 🔨 build |
| `proxy/` | **Caddy** same-origin reverse proxy + CSP for embedding. | ✅ done |
| `db/internal/`, `internal-web/` | The **internal data-quality dashboard** (secondary). | 🔨 build |
| `scripts/` | Grid-reference/CRS utilities, the synthetic seed generator, and the SQL validator. | 🔨 build |
| `docs/` | Architecture, data model, governance, the gate, accessibility, deployment, handover. | ◑ governance done, rest skeleton |
| `.github/`, `Makefile`, `docker-compose.yml`, configs | CI/CD, orchestration, tooling. | ✅ done |

## Quick start

**Prerequisites:** Docker Desktop, Node 20+, Python 3.11+.

```bash
git clone <your-repo-url> brerc-dashboard && cd brerc-dashboard
cp .env.example .env                 # edit passwords; .env is git-ignored

# FRONT END — runs on realistic MOCK data by default, so NO backend is needed:
cd web && npm install && npm run dev # http://localhost:5173

# (Backend teammates) the full stack also starts; it comes alive as the DB/API land:
make up                              # Postgres/PostGIS, Martin, API, web, proxy
make db-migrate                      # applies migrations (0001 works; the rest are the backend owner's)
```

As you complete each part of [`BUILD_PLAN.md`](BUILD_PLAN.md), more of the stack
lights up. When the data layer is in, `make db-seed` and `make gate-test` bring
the map to life.

## How to build it (start here)

1. Read **[`BUILD_PLAN.md`](BUILD_PLAN.md)** — the ordered, step-by-step plan.
2. Each stub file has a `TODO` header telling you exactly what to build, the
   acceptance test, and a pointer to the matching reference.
3. Keep the two hard rules above intact — the tests will tell you if you don't.

> **Reference material** (kept separately, not in this public repo): a full
> worked **Answer Key** implementation and a **Learning Guide** that teaches each
> part. Use them when you're stuck.

## Tech stack

PostgreSQL 16 + PostGIS · Martin (vector tiles) · FastAPI (Python 3.11+, async,
read-only) · React 18 + TypeScript + Vite · MapLibre GL JS + React Aria · Caddy ·
Docker Compose · GitHub Actions + CodeQL + Dependabot.

## Testing & CI

```bash
make lint        # ruff + eslint (incl. jsx-a11y) + sqlfluff
make typecheck   # mypy + tsc
make test        # api unit tests + web unit/accessibility (axe) tests
make gate-test   # the fail-closed sensitive-species gate (needs the DB up)
```

CI runs the same checks on every push/PR (`.github/workflows/`), including a job
that runs the gate against **real PostGIS**, plus CodeQL and Dependabot. The
badges above turn green once your implementation passes.

## Project & team

- **Client:** BRERC (Manager: Tim Corner). **Consultancy:** 180 Degrees
  Consulting Bristol (Head of Data Science: Jaslyn Leong).
- **Team (alphabetical):** Aman (Project Leader), Athul, Michael (**front-end
  owner**), Ting Ting, Victor. The database + backend (PostgreSQL/PostGIS, tiles,
  API) are owned by a teammate — to be assigned. This is a **mono-repo**: each
  area lives in its own folder and everyone works in the same repository.

## Documentation

See [`docs/`](docs/README.md): architecture, data model, **data governance**, the
sensitive-species gate, accessibility (+ statement template), deployment, handover,
and the decision log. Contributor guides: [`CONTRIBUTING.md`](CONTRIBUTING.md) ·
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) · [`SECURITY.md`](SECURITY.md) ·
[`CLAUDE.md`](CLAUDE.md).

## Licence

[MIT](LICENSE) (a sensible default; the final choice rests with BRERC / 180DC —
see [`docs/DECISIONS.md`](docs/DECISIONS.md)).
