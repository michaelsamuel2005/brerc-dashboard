# The sensitive-species gate

> **Skeleton — fill this in as you build `db/migrations/0004` (see `BUILD_PLAN.md`).**
> Reference: Learning Guide Module 2 · Answer Key: `brerc-public-dashboard/docs/SENSITIVE_SPECIES.md`

## The rule (do not weaken — this is binding)

No public output — tile, API response, grid reference, or download — may ever
expose a location finer than allowed for a sensitive record, or any recorder name.
This holds **by construction**: precise data is removed in the database
(`public_occurrences`), and the application role cannot read the precise table.
Generalise (blur to a coarser square), never randomise. Fail closed.

## TODO (document as you implement)
- [ ] How `generalise_point` blurs to the cell centre (floor arithmetic, EPSG:27700).
- [ ] How the effective resolution is chosen (coarsest of baseline / source / sensitive).
- [ ] The control list (`sensitive_species`) and the `public_config` dials.
- [ ] What `db/tests/test_generalisation_gate.sql` asserts.
- [ ] Reminder: BRERC's authoritative list goes in the DB, never in Git.
