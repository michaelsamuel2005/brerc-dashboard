# `internal-web/` — internal data-quality dashboard

A single, dependency-free `index.html` for the **internal** staff dashboard
(brief deliverable 2). It calls the `/internal/*` API and shows content and
data-quality monitoring: totals (records, species, recorders, datasets, year
span), issues by type, an issue list, records by dataset (BLISS), and top
recorders (Recorder1).

## ⚠️ Internal and access-controlled

This tool shows **precise data and recorder names** (personal data). It — and the
`/internal/*` API it calls — must be served **only on the internal network or
behind the council's SSO**, never through the public reverse proxy. The API is
off by default and refuses every request unless `INTERNAL_ENABLED=true` and
credentials are configured (fail-closed). The HTTP Basic prompt here is a minimal
gate, not a replacement for proper authentication.

## Run it

The internal API is opt-in. Enable it (see `.env.example`) and point Martin/API
compose profile `internal`:

```bash
# in .env
INTERNAL_ENABLED=true
INTERNAL_DATABASE_URL=postgresql://brerc_internal_ro:CHANGE_ME@db:5432/brerc
INTERNAL_BASIC_AUTH_USER=staff
INTERNAL_BASIC_AUTH_PASSWORD=CHANGE_ME

make db-internal        # create the internal role + data-quality views
make internal-up        # start the API with the internal profile (not proxied publicly)
```

Then open `internal-web/index.html` (any static host on the internal network),
set the API base URL to the internal API, and sign in. Credentials are held in
memory for the session only — never written to `localStorage`.

## Why a single HTML file?

The internal tool is a secondary deliverable and is handed to non-developer BRERC
staff. One self-contained file with no build step is the most maintainable option
and is trivial to place behind the council's existing internal auth.
