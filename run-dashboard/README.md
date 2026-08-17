# run-dashboard/

A small, standalone read-only viewer for the ETL run-history log written by
`api/etl/run_history.py` (`logs/etl_run_history.db`, gitignored local runtime
state). Shows every "UI ETL RUN" pipeline run — run number, job type
(initial/incremental), date, load no, and status — and auto-refreshes so a
run visibly flips from `running` to `successful`/`failed`.

Kept separate from `api/app` (the public dashboard API, which is deliberately
read-only against the reviewed `serve.*` views only) — this is an internal
ops tool with no database connection of its own; it only reads the local
SQLite file.

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

There is **no default login**. If either credential is missing the app
refuses to start — a dashboard that will not boot is a better failure than
one anyone can log into. (An earlier version of this README described an
`admin`/`admin` fallback; that fallback was removed from the code and the
paragraph is corrected here to match.)

## What writes the log on this branch (open design question)

On `main`, `etl/job.py` calls `start_run()` / `mark_run_successful()` /
`mark_run_failed()` from `api/etl/run_history.py` around each nightly ETL
run. On this branch the pipeline entry point is the `brerc-load` release
loader, which does not yet write this log — so a fresh checkout shows
"No runs recorded yet." until that wiring lands.

Two candidate designs, deliberately left for review rather than decided in
the port:

1. **Keep the SQLite log**: call `run_history.start_run()` /
   `mark_run_*()` from the loader CLI around each release run. Faithful to
   the original design; adds a second, file-based record alongside the
   loader's own release ledger in PostgreSQL.
2. **Read the loader's ledger instead**: adapt `_fetch_runs()` to read the
   release/job bookkeeping the loader already writes to PostgreSQL, and
   retire the SQLite file. One source of truth, but a larger change to this
   app.

Until one is chosen, this app runs, serves its login, and reports an empty
history — it does not error on the missing database file.
