# run-dashboard/

A small, standalone read-only viewer for the ETL run-history log written by
`api/etl/run_history.py` (`logs/etl_run_history.db`, gitignored local runtime
state). Shows every "UI ETL RUN" pipeline run — run number, job type
(initial/incremental), effective load date, and status — and auto-refreshes so a
run visibly flips from `running` to `successful`/`failed`.

Kept separate from `api/app` (the public dashboard API, which is deliberately
read-only against public views only) and from `internal-web/` — this is an
internal ops tool with no database connection of its own; it only reads the
local SQLite file.

Gated behind a single shared login — see **Login** below.

## Run locally

```bash
cd run-dashboard
pip install -r requirements.txt
cp .env.example .env   # then edit .env and set a real DASHBOARD_PASSWORD
uvicorn app:app --reload --port 8100
```

Then open <http://127.0.0.1:8100/> — you'll be redirected to `/login`.

## Login

One shared username/password, set in `run-dashboard/.env` (copy from
`.env.example`, never commit the real file):

- `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` — the login credentials.
- `DASHBOARD_SECRET_KEY` — signs the session cookie. Leave blank for local
  use (a random key is generated each time the app starts, which just means
  everyone's logged out on restart); set a fixed value for anything longer-
  lived.

If either login value is missing, the dashboard refuses to start. There is no
default username or password.

## Legacy status — do not use for production publication

This version of the viewer reads the legacy SQLite log only. The legacy
`etl.job.nightly_job()` writer targets obsolete tables, does not consume the
signed publication-approval artifact and must not drive the reviewed
publication store. Do not run that command as a production or nightly release
procedure.

The reviewed atomic loader writes the authoritative release and run state to
PostgreSQL. Use the loader procedure in
[`docs/POSTGRES_RELEASE_LOADER.md`](../docs/POSTGRES_RELEASE_LOADER.md). Until
the PostgreSQL-backed internal viewer is integrated, inspect that authoritative
run state through the controlled database/operator procedure rather than this
legacy page.
