import pandas as pd

from etl.load.loader import load_safety_config
from etl.profiling.cleaning import clean_data
from etl.reconciliation.hashing import add_content_hash
from etl.reconciliation.diff import build_id_hash_map_from_chunks

CONFIG = load_safety_config()

# Generator function that produces clean dataframe chunks
def iter_source_chunks(source_df=None, chunk_size=None):
    if chunk_size is None:
        chunk_size = CONFIG.get("reconciliation", {}).get("chunk_size", 5000)

    # If a DataFrame is injected directly (e.g. already loaded/resolved
    # upstream, or supplied by a test), chunk that in memory instead of
    # re-reading the source from disk.
    if source_df is not None:
        for start in range(0, len(source_df), chunk_size):
            yield clean_data(source_df.iloc[start:start + chunk_size])
        return

    mode = CONFIG["source"].get("mode", "csv")

    if mode != "csv":
        raise NotImplementedError(
            "iter_source_chunks currently only supports csv mode"
        )

    # Reads the data in chunks
    for raw_chunk in pd.read_csv(
        CONFIG["source"]["records_path"], chunksize=chunk_size
    ):  
        # Clean each chunk
        yield clean_data(raw_chunk)

# Returns dictionary containing every record's unique_name and content_hash 
def build_source_hash_map(source_df=None, chunk_size=None):

    # Nested generator 
    def _hashed_chunks():
        # Loops through the cleaned chunks (uses source_df if given, else streams from disk)
        for cleaned_chunk in iter_source_chunks(source_df, chunk_size):
            # Adds hashes (calculates the hash)
            yield add_content_hash(cleaned_chunk)

    # Processes the cleaned hashed chunks, merging to build final dictionary
    return build_id_hash_map_from_chunks(_hashed_chunks())