# Public serving architecture — safe v1

**Status:** selected v1 architecture; server boundary implemented in PR #52,
browser adapter completed by PR #53

**Decision date:** 20 September 2026

**Scope:** public distribution map and its accessible data equivalent

## Decision

The selected v1 architecture does **not** use Martin or a vector-tile route.
Once the stacked browser-integration PR #53 lands, the public map and its
accessible table must use one authoritative, same-origin API response:

```text
browser
  -> GET /api/distribution/cells?species=...&year=...
  -> read-only FastAPI service
  -> serve.public_distribution_cell
  -> active release selected by loader_control.source_state
```

PR #52 establishes the server side of this boundary. Its endpoint returns
cells without geometry. The browser code on PR #52's branch still expects the
superseded GeoJSON response shape, so PR #52 is not a standalone end-to-end
frontend release. PR #53 must adapt the strict browser schemas and derive
display geometry from the validated public grid-cell identifier before either
PR can be described as a working live integration.

The final React client must call `/distribution/cells` through its `/api` base
URL and must not call `/tiles`. This avoids a split-brain state in which a tile
service and the table could read different stores or releases.

## Privacy and consistency properties

- Only the active atomic release is visible through `serve.*` views.
- The API login must inherit only the reviewed `brerc_api` group role and each
  database session is forced read-only.
- Source eastings, northings and observation coordinates never cross the API
  boundary. The endpoint returns a validated public grid-cell identifier,
  declared precision and approved aggregate counts.
- PR #53's browser adapter derives the display polygon from that public grid
  identifier. It cannot recover the source point from the response.
- Species is mandatory before cells are returned. An unscoped request returns
  an empty collection.
- The API returns at most the configured safe cell limit. If a result exceeds
  it, the whole request fails with HTTP 503; it never publishes a misleading
  partial map.
- The final map and accessible table must consume the same validated cell
  collection, so their species, year, precision and count data cannot diverge
  by storage path. This client-side parity is an acceptance gate for PR #53,
  not a claim that the PR #52 browser already conforms.
- Hover or click interactions may expose only fields already present in that
  aggregate response. They must never add observation latitude/longitude.

The publication policy—not this serving decision—controls which precision
tiers and counts may enter an active release. The serving layer cannot widen
that policy.

## Martin decision

`db/roles.sql` retains a tightly scoped `brerc_martin` group role so a future
reviewed tile service can be added without broadening another consumer's
privileges. That reserved capability is not an active v1 service.

A future Martin proposal must be a separate reviewed change that:

1. reads only active `serve.*` data, never the legacy `public.*` tables;
2. defines a versioned tile function or source explicitly;
3. proves tile/API/table parity for release, filters, cells and counts;
4. proves that coordinates cannot become more precise through tile geometry,
   metadata, caching, errors or interaction payloads;
5. defines cache invalidation at the atomic release switch; and
6. passes privacy, accessibility, load and rollback acceptance tests.

Until all six are satisfied, `/tiles`, `db/b7_tiles.sql` and the legacy Martin
container are outside the supported architecture.

## Excluded legacy scaffold

The root `docker-compose.yml` and `Caddyfile` use the obsolete B6 sample schema,
legacy `public.*` tables, an unpinned Martin image, development credentials and
a text placeholder instead of the React application. They do not create an
active `serve.*` release and cannot satisfy the API's production TLS/session
checks. Every Compose service is therefore behind the explicit
`legacy-obsolete` profile; an ordinary `docker compose up` selects nothing.

They must not be used for:

- production or staging deployment;
- local acceptance evidence;
- real BRERC data, certificates or credentials; or
- recovery or rollback.

The production Linux serving procedure is a separate reviewed deployment
deliverable. It must serve the retained React build and same-origin `/api`, use
private API/database networking and deploy the isolated non-root API image.

## Basemap boundary

This decision covers BRERC distribution data only. The choice of CARTO or a
self-hosted basemap, its request telemetry, attribution, fonts and privacy
notice remains a separate deployment decision. No basemap provider receives
BRERC observation records or source coordinates through this architecture.
