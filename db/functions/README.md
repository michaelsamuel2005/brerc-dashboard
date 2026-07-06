# db/functions

The SQL functions that make up the gate are defined **inside the ordered
migrations**, next to the objects that depend on them, so `make db-migrate`
applies everything in one deterministic pass:

- `generalise_point(geometry, integer)` and `en_to_gridref(double precision,
  double precision, integer)` — in
  [`../migrations/0004_public_occurrences_view.sql`](../migrations/0004_public_occurrences_view.sql).
- `public_occurrences_mvt(z, x, y, query_params)` — the Martin tile function, in
  [`../migrations/0005_tile_functions.sql`](../migrations/0005_tile_functions.sql).
- `refresh_public_occurrences()` — optional, in
  [`../optional/0100_public_occurrences_mv.sql`](../optional/0100_public_occurrences_mv.sql).

This directory is kept as the documented home for that index. If you extract a
function into its own file later, reference it from the migration so ordering
stays explicit.
