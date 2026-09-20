# Internal ETL run-history dashboard

This authenticated, read-only application shows the authoritative job history
written by the atomic PostgreSQL/PostGIS publication loader. It reads only the
security-barrier view `serve.etl_job_status` using a dedicated login that
inherits exactly the `brerc_monitor` role.

It does not read source records, publication tables, raw errors, credentials or
the historical local SQLite log. The public FastAPI/React dashboard remains a
separate service and continues to read only the active `serve.public_*` views.

## Supported update path

Run the one-time first publication with:

```sh
brerc-load initial --config /controlled/path/loader.configuration.yaml
```

Every later scheduled replacement must use:

```sh
brerc-load refresh --config /controlled/path/loader.configuration.yaml
```

`refresh` reads one complete, locked BRERC source snapshot, constructs and
validates an inactive candidate, then atomically switches the active release.
The older `etl.job.nightly_job()` writes legacy tables that the current API
does not read. It is fail-closed outside explicitly acknowledged development
tests and must never be scheduled. The `brerc-load incremental` command also
remains deliberately blocked.

## What the UI shows

The page polls `/api/runs` every five seconds and displays at most the 500 most
recent loader jobs:

- opaque job and source identifiers, attempt number and `initial`/`refresh`
  mode;
- start, finish and bounded duration;
- authoritative lifecycle status;
- safe source, publication-basis and withheld counts;
- the no-change/reused-release outcome; and
- a fixed failure code with repository-owned explanatory text.

Database exception text is never returned to the browser. Operators must use
the protected service logs for diagnostics.

## Production connection contract

Production requires all of the following:

- `DASHBOARD_ENV=prod` so the session cookie is HTTPS-only;
- non-default dashboard credentials and a persistent random session key;
- `RUN_DASHBOARD_DB_MODE=service`;
- absolute paths to a protected libpq service file, passfile and trusted CA;
- the expected destination database name and exact monitor login role;
- `sslmode=verify-full`; and
- a database session whose `current_user` is the expected login, whose default
  transaction mode is read-only, which inherits `brerc_monitor`, and which is
  neither a superuser nor a member of `brerc_loader`, `brerc_api` or
  `brerc_martin`.

The application refuses the connection if any identity or privilege check
fails. The monitor login needs only `CONNECT` plus the permissions inherited
from `brerc_monitor`; migration 0001 grants that role access only to:

- `serve.etl_job_status`;
- `serve.etl_release_status`; and
- `serve.etl_notification_status`.

This UI currently queries the first view only. The other two are the bounded
contract for a future alert evaluator and a separate least-privilege outbox
delivery/acknowledgement worker. Neither worker is created by this UI. A fourth,
external dead-man check must detect a scheduler or host failure that occurs
before the loader can write a database job. Never grant this web process broader
database privileges to implement any of those responsibilities.

## Local synthetic preview

Install the application dependencies:

```sh
cd run-dashboard
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

For a disposable local/test database only, set these values in the untracked
`.env`:

```dotenv
DASHBOARD_USERNAME=choose-a-local-username
DASHBOARD_PASSWORD=choose-a-long-local-password
DASHBOARD_SECRET_KEY=choose-a-random-session-key
DASHBOARD_ENV=test
RUN_DASHBOARD_DB_MODE=direct
RUN_DASHBOARD_DATABASE_URL=postgresql://MONITOR_USER:PASSWORD@localhost:5432/UI_DATABASE?sslmode=verify-full&sslrootcert=/absolute/path/to/ca.crt
RUN_DASHBOARD_EXPECTED_DATABASE=UI_DATABASE
RUN_DASHBOARD_EXPECTED_ROLE=MONITOR_USER
```

Direct DSN mode is rejected when `DASHBOARD_ENV=prod`. Do not place a real DSN
or password in a tracked file, command, screenshot, shell history or ticket.

Start the app and open <http://127.0.0.1:8100/>:

```sh
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8100
```

The page can legitimately show no runs until an `initial` or `refresh` command
has recorded a job in the same destination database.

## Verification

Unit and HTTP-boundary tests run without a database:

```sh
cd run-dashboard
python -m pytest tests -q -m "not integration"
```

CI additionally provisions disposable PostgreSQL 16/PostGIS, performs an
initial publication and a changed full-snapshot refresh, then runs the opt-in
live test as the TLS-authenticated monitor role. That proves the viewer sees
the same successful refresh subsequently served by FastAPI and the mocks-off
browser acceptance.

Full refresh operation and acceptance evidence are documented in
[`../docs/FULL_SNAPSHOT_REFRESH.md`](../docs/FULL_SNAPSHOT_REFRESH.md).

## Historical SQLite component

`api/etl/run_history.py` and `logs/etl_run_history.db` belong to the retained
legacy pipeline. They remain only for provenance and existing development test
coverage. They are not inputs to this application, are not a production audit
record and must not be populated by scheduling the legacy nightly job.
