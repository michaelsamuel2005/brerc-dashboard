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

The versioned publication-safety boundary is implemented in `api/etl`. The
trusted PostgreSQL source connector captures the approved view identity and
streams rows from the same locked, read-only snapshot. Its deployment and
operation are documented in
[`docs/POSTGRES_SOURCE_CONNECTOR.md`](../docs/POSTGRES_SOURCE_CONNECTOR.md).
It is fully exercised with synthetic PostgreSQL 16/TLS fixtures; a real BRERC
acceptance run remains a controlled production activity.

Run the source-connector checks from this directory:

```bash
python -m pip install ".[connector-binary]"
python -m unittest discover -s connector_tests -t . -p 'test_*.py'
```

## What does **not** go here

- ❌ Front‑end / UI code — that lives in `../web`.
- ❌ The database schema itself — that lives in `../db`.
- ❌ Real secrets or `.env` files committed to git — keep credentials out of the repo.

## Species images & descriptions (B8)

`/api/species/{id}` can show a photo and a short description. BRERC holds no
photographs, so these are borrowed from public natural-history APIs by
[`app/species_info.py`](app/species_info.py) — the one place the licence rules
live.

**How it decides.** It tries **iNaturalist → GBIF → Wikipedia** and stops at the
first photo that passes the gate. A photo is only shown when *all three* hold: a
permitted licence, a usable attribution, and an HTTPS url. Anything else — an
NC-licensed photo, a blank licence, a missing credit — means **no image**, which
is the correct, deliberate outcome. The front end should then show a named
placeholder, never a broken image.

**Switching it on.** Off until you set both `SPECIES_INFO_ENABLED=true` and
`SPECIES_INFO_CONTACT` (see [`.env.example`](.env.example)). The contact is
required because these APIs ask callers to identify themselves in the
User-Agent. With it off, endpoints still work and simply return `image: null`.

**What licences pass.** By default `cc0`, `pd`, `cc-by` only — the safe set for a
public site that may become commercial. In practice most iNaturalist photos are
CC BY-NC and most Wikipedia/Commons files are CC BY-SA, so both are refused and
GBIF supplies most of the coverage. If BRERC confirms share-alike images are
acceptable, adding `cc-by-sa` to `SPECIES_IMAGE_ALLOWED_LICENCES` unlocks the
Wikipedia source; that env var is the entire change, and the cache re-fetches
itself because the licence rules form part of its key.

**Caching.** Answers are cached in memory and in a small SQLite file
(`api/.cache/`, git-ignored; a Docker volume in `docker-compose.yml`), because
the API connects as a read-only database role and so cannot cache in PostgreSQL.
Third parties are never called per page view.

**Open contract question for the front end.** Wikipedia text is CC BY-SA, which
requires attribution and a link back, but `SpeciesDetail.description` is a plain
string with nowhere to put them — so the credit is appended to the sentence
itself. If a `descriptionSource` field can be added to the agreed contract, move
it there and drop the suffix.

## Helpful links

- 🗂️ [Project structure](../docs/PROJECT_STRUCTURE.md) — what every folder is for.
- 🔐 [BRERC source-view contract](../docs/SOURCE_CONTRACT.md) — the reviewed
  source schema, safety mapping and incremental-load blockers.
- 🔏 [Live view approval](../docs/VIEW_DEFINITION_APPROVAL.md) — the secure
  capture, digest and named approval procedure.
- 🔌 [Trusted PostgreSQL connector](../docs/POSTGRES_SOURCE_CONNECTOR.md) —
  least-privilege deployment, safe operation and scale limitations.
- 🐙 [Getting started with GitHub](../docs/GETTING_STARTED_GITHUB.md) — branch, push, open a PR (no prior experience needed).
