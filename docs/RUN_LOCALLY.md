# Running the dashboard on your own machine

Three ways to look at the front end, in order of how much you need running.
Every command below was executed before it was written down; where something
has **not** been verified, it says so.

| | What you see | What it needs | Start-up |
|---|---|---|---|
| **A. Mock data** | The whole UI, fixture data | Node 20+ | ~10 seconds |
| **B. Real API, built app** | The production topology, real published data | A + Python API + a publication database | a few minutes |
| **C. Real API, dev server** | Same, with hot reload | Same as B | a few minutes |

**A is the right choice for a demo.** It has no database, no network and no
moving parts, so it cannot fail in front of an audience. Everything on screen is
the real front-end code — routing, the map, the tables, the accessibility
behaviour — fed by fixtures instead of Postgres. The app labels itself
`PROTOTYPE` and the footer says *illustrative demo data*, so nobody is misled.

Use **B** when the question is "does the front end agree with what the API
actually returns", which is the question the mock cannot answer.

---

## A. Mock data — no backend

```bash
cd web
npm install          # first time only
npm run dev
```

Open **http://localhost:5173**. It redirects to `#/species`.

Three species (Adder, Common lizard, Slow-worm) come from the MSW fixtures in
`web/src/test/msw/`. The mock intercepts `fetch` in the browser, so nothing
listens on a database port and the app works with the network off.

---

## B. Real API and a real publication database

Three things run: Postgres holding a publication release, the FastAPI service
reading it, and the built front end served with `/api` proxied to that service.

### B1. A publication database

You need a PostgreSQL 16 + PostGIS 3.5 database with the publication schema and
an **activated release**. If you already have one — the destination database
from the loader integration run is exactly this — skip to B2 and point
`DATABASE_URL` at it.

Otherwise `deploy/docker-compose.yml` brings up an empty one:

```bash
cp deploy/.env.example deploy/.env    # fill in every value
cd deploy && docker compose up -d db
```

Empty is a real state, not a broken one: until a release is activated the API
answers **503 `No active publication release`** (`api/app/release.py:56`) and
the dashboard shows an error rather than an empty map. That is deliberate — it
distinguishes "nothing published yet" from "something is broken".

Publishing a release is the loader's job, not this app's, and it is the one step
that is **not** a single command. See `docs/POSTGRES_RELEASE_LOADER.md`. The
loader requires TLS with certificate verification against the source and the
destination, so it needs the configured environment described there.

> **There is no shortcut here on purpose.** A "quick seed" script that inserted
> straight into `publication.*` would bypass `activate_validated_release` and
> every safety gate behind it, and would then exist in the repository as a
> ready-made way to publish unchecked data. Standing up the real environment is
> slower and stays honest. What is missing is a scripted developer environment,
> not a looser one — see *Known gap* at the end.

### B2. The API

From `api/`, with your own connection string:

```bash
cd api
python3 -m pip install -e .          # first time only
DATABASE_URL='postgresql://brerc_api:PASSWORD@127.0.0.1:5432/brerc_publication' \
APP_ENV=prod \
ALLOWED_ORIGINS= \
  python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check it:

```bash
curl -s http://127.0.0.1:8000/api/health     # {"status":"ok","version":"0.1.0"}
```

Use the **read-only** role, not the loader's and not `postgres`.
`api/app/db.py` verifies the session is read-only and refuses to serve
otherwise, so a writable role fails loudly rather than working by accident.

`APP_ENV=prod` with an empty `ALLOWED_ORIGINS` is the production configuration,
and it works locally because of the proxy in the next step: the browser only
ever calls the same origin it loaded the page from, so no CORS permission is
needed. Running the production configuration locally is the point — a setting
that only works in dev has not been tested.

### B3. The front end

```bash
cd web
npm run build
npm run preview
```

Open **http://localhost:4173**.

The built app never loads the mock layer, so what you see is the API's own data.
`vite.config.ts` forwards `/api` to `http://127.0.0.1:8000`, which reproduces
the same-origin shape the reverse proxy gives in production (D-001) — the same
relative `/api` path, no CORS, no build-time API URL. If your API is somewhere
else:

```bash
BRERC_LOCAL_API=http://127.0.0.1:9000 npm run preview
```

`BRERC_LOCAL_API` has deliberately no `VITE_` prefix: `VITE_`-prefixed variables
are inlined into the shipped JavaScript, and this one must stay on your machine.

---

## C. Real API with hot reload

Same backend as B, but the dev server instead of a build:

```bash
cd web
VITE_USE_REAL_API=1 npm run dev
```

Open **http://localhost:5173**. Same `/api` proxy, same real data, but edits
reload instantly. Without the flag, `npm run dev` uses the mock — that is the
default and stays the default.

A production build ignores this variable entirely. `src/main.tsx` returns on a
literal `import.meta.env.DEV` check *before* anything imports MSW, so the mock
is eliminated from the bundle at build time rather than merely switched off, and
`npm run guard:bundle` fails the build if that ever stops being true. The rule
itself is unit-tested in `src/app/mocking.test.ts`.

---

## If something does not work

| Symptom | Cause |
|---|---|
| Blank page, console shows failed `/api/...` calls | The API is not running, or is on a different port. Check `curl http://127.0.0.1:8000/api/health`. |
| `503 No active publication release` | The database has no activated release. Correct behaviour — see B1. |
| Species list is Adder / Common lizard / Slow-worm when you wanted real data | You are on the mock. Use `npm run preview` (B) or `VITE_USE_REAL_API=1` (C). |
| API exits at startup in `prod` | `DATABASE_URL` is unset. It refuses rather than falling back to a local database. |
| API starts but every request fails | The role can write. `app/db.py` requires a read-only session. |
| Map squares appear over a blank background | The CARTO basemap tiles could not be fetched. The data layer is fine; the basemap is a third-party CDN and needs internet access. |
| Port already in use | `npm run dev -- --port 5180`, or stop the other process. |

---

## Known gap

There is no single command that produces a fully populated local stack, because
the only safe way to populate one is to run the loader, and the loader needs a
TLS-configured source and destination.

Closing it properly means a scripted developer environment — generate a local
CA, start Postgres with TLS, apply `db/roles.sql` and
`db/migrations/0001_publication_store.sql`, load a small synthetic source through
the real loader — reproducing the required configuration rather than relaxing
it. That is worth doing before handover, since BRERC's maintainer will need it
too, and it is tracked rather than quietly worked around.

---

## What this does not cover

Deploying to a server, HTTPS, and the link from BRERC's website:
**`docs/DEPLOYMENT.md`**.
