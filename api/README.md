# API — read-only FastAPI service

A thin, read-only service over the `public_occurrences` gate. It never touches
precise data: it connects as `brerc_readonly` (which cannot read the precise
table) and every query selects from the generalised view.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Readiness (200 ok / 503 if DB down). |
| GET | `/species/search?q=&limit=` | Species autocomplete (blocked taxa never appear). |
| GET | `/species/filters` | Taxon groups, datasets, and the year range for filters. |
| GET | `/occurrences/summary` | Public-safe headline counts. |
| GET | `/occurrences/cells?scientific_name=&taxon_group=&year_from=&year_to=&min_lon=&…` | Generalised, counted grid cells — the **accessible table equivalent of the map**. |
| GET | `/species-info?scientific_name=` | Cached image (licence fail-closed) + description. |

Interactive docs: `/docs` (or `/api/docs` behind the proxy).

## Design guarantees

- **Read-only, two ways:** the DB role is read-only and cannot see `occurrences`;
  the app also opens read-only transactions with a statement timeout.
- **Parameterised SQL only.** No string-built queries from user input.
- **Row-capped.** `/occurrences/cells` caps results and flags truncation.
- **Species images fail closed.** Only images with a confirmed reusable licence
  (default allow-list: CC0 / CC BY / public domain) are returned; otherwise the
  response has `has_image=false` and the UI shows a placeholder.

## Run locally (without Docker)

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export PUBLIC_DATABASE_URL=postgresql://brerc_readonly:...@localhost:5432/brerc
uvicorn app.main:app --reload
```

## Test, lint, type-check

```bash
pytest            # unit tests run offline; DB-backed tests skip without PUBLIC_DATABASE_URL
ruff check app tests
mypy app
```

The species-info tests mock all third-party HTTP with `httpx.MockTransport`, so
they are deterministic and offline. The DB integration test
(`tests/test_generalisation_gate.py`) runs only when `PUBLIC_DATABASE_URL` points
at a migrated + seeded database.
