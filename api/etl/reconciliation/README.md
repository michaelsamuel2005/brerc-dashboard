# Legacy occurrence-table reconciliation

> **Historical development/test path only.** This package contains Ting Ting's
> retained reconciliation implementation for the old `occurrence_public`
> tables. The entry point that used it, `etl.job.nightly_job()`, is fail-closed
> outside explicitly acknowledged development/tests and must never be scheduled
> for the current dashboard.

The production-shaped update command is `brerc-load refresh`. It reads one
complete, locked source snapshot, creates and validates an isolated candidate,
and atomically replaces the active `serve.*` release. `brerc-load incremental`
remains blocked. A source deletion is represented by absence from that complete
replacement snapshot, not by inferring a delete from a partial window. See
[`../../../docs/FULL_SNAPSHOT_REFRESH.md`](../../../docs/FULL_SNAPSHOT_REFRESH.md).

The historical implementation remains useful as regression-covered provenance:

- `hashing.py` produced deterministic content hashes.
- `diff.py` classified insert/update/delete sets.
- `streaming.py` processed source files in chunks.
- `state.py` read the existing legacy database state.
- `map_to_schema.py` mapped data into the legacy table shape.
- `reconcile.py` coordinated the old two-pass diff.
- `load.py` applied staged upserts and deletes directly to
  `occurrence_public`.

These modules do not write the release-scoped `publication.*` tables consumed
by FastAPI and do not populate the authoritative PostgreSQL run-history views.
Preserving them and their authorship does not make them an operational fallback.
