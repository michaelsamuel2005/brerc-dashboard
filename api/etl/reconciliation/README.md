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