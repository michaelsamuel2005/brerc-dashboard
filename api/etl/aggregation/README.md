# Legacy aggregation modules

> **Historical development/test path only.** These pandas modules built the old
> `species` and `distribution_cell` tables. They remain for provenance and
> regression tests; they are not the PostgreSQL/PostGIS publication store used
> by the current FastAPI application.

The old flow filtered verification states, binned coordinates, applied its
configuration threshold, built a species index and truncated/reloaded the
active `distribution_cell` table. Scheduling that behavior would risk exposing
a partial or incomplete update, so `etl.job.nightly_job()` is now blocked by
default and always blocked in production.

Current publication uses `brerc-load initial` once and `brerc-load refresh` for
later complete replacements. Aggregates are built under an inactive release;
PostgreSQL validates the entire candidate before one atomic active-release
switch. `brerc-load incremental` remains deliberately blocked. See
[`../../../docs/FULL_SNAPSHOT_REFRESH.md`](../../../docs/FULL_SNAPSHOT_REFRESH.md).
