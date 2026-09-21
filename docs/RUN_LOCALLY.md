# Run the dashboard locally

This guide covers two supported development modes: the browser-only synthetic
mock and the full browser-to-FastAPI path against an already provisioned local
publication database.

> Use synthetic data only. Never put real BRERC records, coordinates,
> credentials or controlled evidence in Git, screenshots or terminal output.

The root `docker-compose.yml` and `Caddyfile` are archived legacy scaffolding.
They use the obsolete database shape and are deliberately disabled by default;
do not use them for local acceptance or deployment.

## Prerequisites

- Node.js 20 or newer;
- npm;
- Python supported by `api/pyproject.toml` when running the API; and
- for live mode, a PostgreSQL/PostGIS database containing one active synthetic
  release in the reviewed `serve.*` views and a login inheriting only
  `brerc_api`.

Install from the lockfile rather than updating dependencies:

```sh
cd web
npm ci
```

## Mode 1 — browser with synthetic mock data

This is the quickest UI-development mode. The mock exists only in Vite's
development build and the bundle guard proves it cannot enter production.

```sh
cd web
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173/`. Leave `VITE_USE_REAL_API` unset; setting it to
`1`, `true` or `yes` disables the mock.

## Mode 2 — browser through the live local API

The publication database and initial synthetic release must already exist. The
source/loader setup and atomic release lifecycle are documented in
[`POSTGRES_RELEASE_LOADER.md`](POSTGRES_RELEASE_LOADER.md). Do not substitute
the archived root Compose schema.

In terminal 1, start FastAPI from `api/`. Supply the local read-only connection
through your protected environment; do not paste a real password into this
document or commit an `.env` file.

```sh
cd api
python -m venv .venv
source .venv/bin/activate
python -m pip install --disable-pip-version-check ".[api]"

export APP_ENV=dev
export DATABASE_URL="$BRERC_LOCAL_DATABASE_URL"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`BRERC_LOCAL_DATABASE_URL` is an illustrative shell variable. Its login must
inherit exactly the `brerc_api` group. If the optional `api_readonly` block in
`config/safety.yaml` is populated, it takes precedence over `DATABASE_URL`.

Check the API endpoint—not the API root, which intentionally returns 404:

```sh
curl --fail --silent --show-error http://127.0.0.1:8000/api/health
```

In terminal 2, disable the development mock and let Vite proxy same-origin
`/api` requests to FastAPI:

```sh
cd web
BRERC_LOCAL_API=http://127.0.0.1:8000 \
  VITE_USE_REAL_API=1 \
  npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173/`. Browser requests remain same-origin at `/api`;
`BRERC_LOCAL_API` is a server-only Vite setting and is never bundled.

## Preview the production browser bundle

A production build never includes or starts the mock, so
`VITE_USE_REAL_API` is unnecessary:

```sh
cd web
npm ci
npm run build
npm run guard:bundle
BRERC_LOCAL_API=http://127.0.0.1:8000 \
  npm run preview -- --host 127.0.0.1 --port 4173 --strictPort
```

Open `http://127.0.0.1:4173/`. This is a local review server, not the production
deployment procedure.

## Required checks before sharing a result

```sh
cd web
npm run typecheck
npm run lint
npm run guard
npm run test:run
npm run build
npm run guard:bundle
```

For browser coverage, install the pinned Playwright browsers and run the full
suite:

```sh
npm run e2e:install
npm run e2e:all
```

Optional reviewer tools are deliberately separate from the mandatory fast CI
path:

```sh
npm run screenshots:review
python3 mutation/run_disposable.py --max-mutants 1
```

The screenshot tool writes only to the ignored `web/screenshots/` directory.
The focused accessibility mutation harness runs in a disposable copy and writes
ignored reports under `web/test-results/a11y-mutation/`. CI syntax-checks both
tools; a complete mutation sweep remains an explicit, time-consuming review
activity rather than a per-commit gate.

## Common failures

- **Port already in use:** stop the old server or choose another port; keep
  `BRERC_LOCAL_API` aligned with the API port.
- **404 at `http://127.0.0.1:8000/`:** expected. Use `/api/health` or another
  documented `/api/*` route.
- **503 or empty dashboard:** confirm the database has exactly one active
  synthetic release and the API login passes its read-only role checks.
- **The browser still shows fixture species:** restart Vite with
  `VITE_USE_REAL_API=1`; changing that flag requires a restart.
- **Production build contains mock code:** stop. Do not share or deploy it;
  `npm run guard:bundle` must pass.
