# run-dashboard/

A small, standalone read-only viewer for the ETL run-history log written by
`api/etl/run_history.py` (`logs/etl_run_history.db`, gitignored local runtime
state). Shows every "UI etl run" pipeline run — run number, job type
(initial/incremental), date, load no, and status — and auto-refreshes so a
run visibly flips from `running` to `successful`/`failed`.

Kept separate from `api/app` (the public dashboard API, which is deliberately
read-only against public views only) and from `internal-web/` — this is an
internal ops tool with no database connection of its own; it only reads the
local SQLite file.

## Run locally

```bash
cd run-dashboard
pip install -r requirements.txt
uvicorn app:app --reload --port 8100
```

Then open <http://127.0.0.1:8100/>.

If the ETL job hasn't run yet, the page shows "No runs recorded yet." — run
it from `api/` with:

```bash
python -c "from etl.job import nightly_job; nightly_job()"
```
