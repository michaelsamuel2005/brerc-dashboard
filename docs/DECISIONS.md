# Decision log

The settled decisions for this repository. **Do not re-litigate a decision here.**
To change one, add a new entry that explicitly **supersedes** the old (reference
its ID), with the reason. Newest first. This mirrors the engagement's
`Decisions_Log.md`; where they differ, the engagement log is the source of truth.

Status values: `Decided` · `Decided (pending confirmation)` · `Superseded by D-XXX`.

---

### D-008 — Repository is public, by the owner's decision (repo-specific) [Decided]
Decision: This repository is published publicly at the dashboard owner's explicit
instruction. It is built to be **safe to be public**: synthetic seed data only,
no secrets, no authoritative sensitive-species list, and security that does not
rely on the code being secret (the gate works because precise coordinates never
enter a tile or API response, not because anyone can't read the SQL).
Consequences: Everyone must keep it safe to be public — never commit `data/`,
`.env`, or BRERC's real sensitive-species list. See `SECURITY.md` and
`HANDOVER.md`.
Note: The engagement's `Data_Governance_and_Compliance.md` §6 states a **private**
repo during the live engagement. Publishing is BRERC's and 180DC's call; this
entry records that the owner chose to publish. Confirm with the BRERC Manager and
the 180DC leads if that is not settled on your side.

### D-007 — Internal dashboard is a separate, access-controlled tier (repo-specific) [Decided]
Decision: The internal data-quality dashboard reads precise data and recorder
names through a **separate `brerc_internal_ro` role** and a **separate API
service** that is off by default, HTTP-Basic gated, localhost-bound, and **never
behind the public proxy**.
Rationale: The internal tool legitimately needs PII (operational need), but that
must not touch the public tier. Physical separation (distinct role + distinct
service) is stronger than a code flag.
Consequences: Public and internal never share a process or a DB role.

### D-006 — Plotly Dash retained as fallback [Decided]
Decision: If the custom front-end build outruns the clock, switch the
presentation layer to Plotly Dash, keeping the same PostGIS + Martin tile layer
and the server-side generalisation gate. Not built unless invoked.
Consequences: The data layer stays presentation-agnostic so only the front end
swaps.

### D-005 — Dev→prod is a credentials-only change [Decided]
Decision: All serving reads use a single `PUBLIC_DATABASE_URL` and a read-only DB
role; moving from the dev database to BRERC production is only a
credentials/connection change.
Consequences: No hard-coded connections; no environment-specific query logic.

### D-004 — Recorder PII off the public tier [Decided]
Decision: `Recorder1` and any personal data are omitted or aggregated on the
public dashboard; full names only on the access-controlled internal tool.
Consequences: `public_occurrences` must not expose recorder identity.

### D-003 — WCAG 2.2 AA is a hard requirement [Decided]
Decision: The public dashboard targets WCAG 2.2 AA and ships a gov.uk-model
accessibility statement; essential map information has an accessible non-map
equivalent (a filterable data table).
Rationale: BRERC is part of Bristol City Council; the Public Sector Bodies
Accessibility Regulations 2018 require WCAG 2.2 AA. Legal, not optional.

### D-002 — Sensitive-species generalisation is enforced server-side, fail-closed [Decided]
Decision: Precise locations of sensitive species are generalised in the database
(`public_occurrences` view using PostGIS floor-to-cell in `EPSG:27700`) before
any tile or API response is produced; the default for anything unconfirmed is to
generalise.
Consequences: Public tiles/APIs read only from the generalised view; an automated
test asserts no finer-than-allowed geometry can be returned for a known sensitive
taxon.

### D-001 — Public dashboard architecture [Decided (pending confirmation)]
Decision: Custom **React + TypeScript** front end with **MapLibre GL JS**;
**PostgreSQL/PostGIS** with server-side sensitive-species generalisation; **vector
tiles via Martin**; a thin **read-only FastAPI** service; deployed **same-origin
behind a reverse proxy**; **WCAG 2.2 AA** target.
Rationale: WCAG 2.2 AA is legally required and only a custom front end gives full
DOM/ARIA control (Streamlit and HoloViz Panel are documented as framework-blocked
for public AA; Dash reaches AA only for page chrome). Vector tiles scale from
thousands to millions of points and let generalisation run server-side. Full
analysis in `ARCHITECTURE.md`.
Depends on three BRERC confirmations (see `ARCHITECTURE.md` §Open questions).
