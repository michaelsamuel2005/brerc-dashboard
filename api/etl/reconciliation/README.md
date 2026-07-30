HASHING
_normalised_hash_value():
    - If value is missing return empty string
    - If value is date/time -> convert to ISO format
    - For everything else, convert to text, remove extra space (from start/end)

row_content_hash():
    - Pulls row values in fixed order 
    - Normalises them
    - Joins values into one string
    - Converts strings into bytes
    - Produces the final hash string

add_content_hash():
    - Adds content_hash column, stores every records hash
    - Runs row_content_hash() on each row
    - Stores results in a new column 


RECONCILE
build_id_hash_map():
    - Builds dictionary:
        - Each record id with its current content hash

diff_id_hash_maps():
    - Compares current source data with whats in UI table
    - Gets all IDs in the new source data
    - Gets all IDs in the UI database 
    - Inserts: IDs in source, but not in UI
    - Deletes: IDs in the UI, but no longer in the source
    - Possible_updates: ID that exist in both (may have changes)
    - For IDs in both, compare the hashes
        - If hashes are different underlying raw row has changed -> update record
    - Unchanged: Records whos hashes are same in both

NEED TO IDENITFY THE RECONCILIATION INPUTS LATER
"""

RECONCILIATION: 
"""
Nightly reconciliation pipeline.

Compares the latest BRERC source data against the UI database,
identifies inserts, updates and deletes, then ensures every new
or changed record passes through the safety gate before being
loaded into the public database.


# Safety pipeline:
# Raw records
#   ↓
# Species resolution
#   ↓
# Sensitivity classification
#   ↓
# Coordinate generalisation
#   ↓
# Coarse locality generation
#   ↓
# Public-column filtering
#   ↓
# Database schema mapping


""" DIFF
Compares the current source dataset with the UI database using
content hashes.

Each record is identified by its unique_no.

The comparison determines which records should be:
- inserted,
- updated,
- deleted, or
- left unchanged.

Only records requiring inserts or updates are returned for
the safety pipeline.
"""

MAP TO sdddsa

"""
    Maps the safety pipeline's output (PUBLIC_COLUMNS shape) onto
    occurrence_public's real column names (db/b6_schema.sql).

    grid_ref and locality are both sourced from coarse_locality today
    (grid square only - unitary authority data doesn't exist yet, see
    add_coarse_locality's own note). They will diverge naturally once
    that data lands: grid_ref stays grid-square-only, locality
    becomes the fuller "authority + grid square" D0 description. No
    code change needed here when that happens - just a richer
    coarse_locality value flowing through the same column.

    verified = NOT is_legacy. Safe because filter_accepted_records's
    accepted/legacy masks are mutually exclusive by construction.
"""


LOAD:

"""
    Real DB writes against Victor's B6 draft schema (db/b6_schema.sql),
    specifically the occurrence_public table.

    OPEN QUESTIONS FOR VICTOR (confirm before relying on this):
      1. occurrence_public has no content_hash column yet - needed
         for D7 reconciliation to diff against next run. Needs adding:
             ALTER TABLE occurrence_public ADD COLUMN content_hash TEXT;
      2. occurrence_public.species_id has a FK to species(species_id).
         Species rows must be upserted into `species` BEFORE any
         occurrence_public write, or inserts will fail on the FK.
         (This file assumes that's handled separately - see
         upsert_species below - call it first in the orchestrator.)

    Uses upsert (INSERT ... ON CONFLICT DO UPDATE) for both insert
    and update - simpler than two code paths, and makes a re-run
    naturally idempotent even for edge cases (e.g. a record that
    was deleted then re-added with the same id).


    """
Database write functions for the reconciliation pipeline.

Records reaching this module have already passed through the
safety gate and been mapped to the public database schema.

Responsibilities:
- Upsert species metadata.
- Insert or update public occurrence records.
- Delete records removed from the source dataset.
"""

    """
    Must run BEFORE insert_records/update_records, since
    occurrence_public.species_id has a foreign key to this table.
    """


    # D5: verified-only + legacy-flagged-not-dropped, BEFORE anything
    # else runs. A record failing both accepted and legacy checks
    # must never reach classification, generalisation, or the DB.
"""
