# 🔌 api/ — Back-end API

The **back-end API**. It talks to the database, and serves only **safe,
non‑sensitive data** to the front‑end over HTTPS.

**Owner:** [TO BE CONFIRMED]
**Status:** 🟡 In development

> 🔒 **This is the safety boundary.** The API decides what leaves the database.
> It must **never** expose precise locations of sensitive species or any personal
> data (e.g. recorder names). Filter, generalise, or remove that data here — the
> front‑end can only show what this layer sends it.

## What goes here

- API endpoints that the front‑end calls.
- Database queries (parameterised — never build SQL by pasting in user input).
- The logic that strips or generalises sensitive data before it is served.

The versioned ETL safety boundary is implemented as the installable `etl` Python package in
`api/etl`. The trusted PostgreSQL initial-load connector obtains live view evidence and rows in
one locked, read-only snapshot; its deployment procedure is documented in
`../docs/POSTGRES_SOURCE_CONNECTOR.md`. It is unit-tested without BRERC data but has not yet been
run inside BRERC's network. The public PostGIS schema, database writer, FastAPI service and Martin
vector-tile service are still future work, so this directory is not a complete running backend.
Its `preflight` operation can check the live identity/schema/header without fetching source rows;
under the current unapproved source contract it must report `release_ready=False`.

Run the current backend gates from this directory:

```bash
python -m unittest discover -s tests -t . -p 'test_*.py'
python scripts/guard_stdlib_only.py --etl-dir etl
python -m pip install ".[connector-binary]"
python -m unittest discover -s connector_tests -t . -p 'test_*.py'
```

## What does **not** go here

- ❌ Front‑end / UI code — that lives in `../web`.
- ❌ The database schema itself — that lives in `../db`.
- ❌ Real secrets or `.env` files committed to git — keep credentials out of the repo.

## Helpful links

- 🗂️ [Project structure](../docs/PROJECT_STRUCTURE.md) — what every folder is for.
- 🔐 [BRERC source-view contract](../docs/SOURCE_CONTRACT.md) — the exact 39-column
  source schema, safety mapping and incremental-load blockers.
- 🔏 [Live view approval](../docs/VIEW_DEFINITION_APPROVAL.md) — the secure capture,
  digest and named BRERC approval procedure.
- 🔌 [Trusted PostgreSQL connector](../docs/POSTGRES_SOURCE_CONNECTOR.md) — transaction,
  least-privilege deployment, safe operation and honest scale limitations.
- 🐙 [Getting started with GitHub](../docs/GETTING_STARTED_GITHUB.md) — branch, push, open a PR (no prior experience needed).
