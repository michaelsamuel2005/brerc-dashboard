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