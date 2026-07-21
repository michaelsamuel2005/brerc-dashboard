# BRERC API — FastAPI scaffold (B0)

Read-only API for the public dashboard. Every endpoint currently returns
**fake data in the exact shape of the agreed contract (§10)** so the front end
can integrate now. Real queries against `public_occurrences` come in B8 — the
response shapes will not change.

## Run it locally

From inside the `api/` folder:

```bash
# 1. (first time) create + activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

# 2. install dependencies
python -m pip install -r requirements.txt

# 3. run the API
uvicorn app.main:app --reload
```

Then open **http://127.0.0.1:8000/docs** — an interactive page listing all 8
endpoints. Click any endpoint → "Try it out" → "Execute" to see the response.

## The 8 endpoints (contract §10)

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{status, version}` |
| `GET /api/summary` | totals, yearRange, recordsByYear[], topGroups[], coverageCaveat |
| `GET /api/species` | paginated species items[] |
| `GET /api/species/{id}` | one species' detail + optional licensed image |
| `GET /api/distribution/cells` | GeoJSON grid cells (WGS84) |
| `GET /api/records` | paginated records (generalised) |
| `GET /api/meta/provenance` | sources, caveats, last-updated, policy summary |
| `.../tiles/{z}/{x}/{y}.mvt` | **served by Martin (B7), not this app** |

## Safety note

Public responses never include `Recorder1`, `BLISS`, `Eastings`, `Northings`,
`Comments`, or any sensitivity marker. When wiring real data (B8), the API reads
only from the `public_occurrences` view, which enforces this server-side.
