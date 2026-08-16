# run-dashboard/

A small, standalone read-only viewer for the ETL run-history log written by
`api/etl/run_history.py` (`logs/etl_run_history.db`, gitignored local runtime
state). Shows every "UI ETL RUN" pipeline run — run number, job type
(initial/incremental), date, load no, and status — and auto-refreshes so a
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

If `.env` is missing entirely, the app falls back to `admin` / `admin` —
fine for a quick local check, not for anything real.

If the ETL job hasn't run yet, the page shows "No runs recorded yet." — run
it from `api/` with:

```bash
python -c "from etl.job import nightly_job; nightly_job()"
```
