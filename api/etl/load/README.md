# Legacy table-loader modules

> **Historical development/test path only.** These modules support the retained
> `occurrence_public` pipeline and its regression tests. `etl.job.nightly_job()`
> is blocked by default and cannot run in production, even if its test opt-in is
> set. Never schedule it or use it to update the current dashboard.

The production-shaped publication path is `brerc-load initial` once, followed
by `brerc-load refresh`. It writes a complete inactive PostgreSQL/PostGIS
candidate and switches `serve.*` atomically after validation. The separate
`brerc-load incremental` command remains deliberately blocked. See
[`../../../docs/FULL_SNAPSHOT_REFRESH.md`](../../../docs/FULL_SNAPSHOT_REFRESH.md).

The retained legacy files exist for provenance and test coverage:

- `loader.py` reads the old `config/safety.yaml` format.
- `mode.py` chose initial versus watermark-based incremental behavior.
- `metadata.py` stamped legacy `Load`/`Load_date` values and queried a
  watermark.
- `reload.py` rebuilt the legacy B6 schema with a separate admin credential.

In that old flow, an initial run could drop/recreate the B6 schema and the
reconciliation/aggregation code could update active tables directly. Those
behaviors are not the current release architecture and are unsafe as a
substitute for atomic refresh. Under the supported mechanism, a removed source
row disappears only because it is absent from the next complete candidate; the
active release is never truncated or partially reconciled in place.
