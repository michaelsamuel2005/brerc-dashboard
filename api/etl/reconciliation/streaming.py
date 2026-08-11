"""
Memory-efficient chunked source data streaming, cleaning, and content hash mapping 
for the reconciliation pipeline. Supports both in-memory DataFrames and disk-based CSV streaming.
"""

import pandas as pd

from etl.load.loader import load_safety_config
from etl.profiling.cleaning import clean_data
from etl.reconciliation.hashing import add_content_hash
from etl.reconciliation.diff import build_id_hash_map_from_chunks

CONFIG = load_safety_config()


# Generator function that produces clean dataframe chunks
def iter_source_chunks(source_df=None, chunk_size=None):
    """
    Generator function that yields cleaned dataframe chunks. 
    Can process an in-memory DataFrame or stream directly from a CSV file defined in safety.yaml.
    """
    if chunk_size is None:
        chunk_size = CONFIG.get("reconciliation", {}).get("chunk_size", 5000)

   # If a DataFrame is injected directly (e.g., from upstream or tests), chunk that in memory
    if source_df is not None:
        for start in range(0, len(source_df), chunk_size):
            yield clean_data(source_df.iloc[start : start + chunk_size])
        return

    mode = CONFIG["source"].get("mode", "csv")

    if mode != "csv":
        raise NotImplementedError("iter_source_chunks currently only supports csv mode")

    # Read source data in memory-safe chunks from disk and clean each chunk on the fly
    for raw_chunk in pd.read_csv(
        CONFIG["source"]["records_path"], chunksize=chunk_size
    ):
        # Clean each chunk
        yield clean_data(raw_chunk)


def build_source_hash_map(source_df=None, chunk_size=None):
    """
    Builds and returns a master dictionary mapping every record's unique identifier 
    to its computed content hash across all streamed source chunks.
    """

    # Nested generator
    def _hashed_chunks():
        # Loop through cleaned chunks and append content hashes to each
        for cleaned_chunk in iter_source_chunks(source_df, chunk_size):
            # Adds hashes (calculates the hash)
            yield add_content_hash(cleaned_chunk)

    # Processes the cleaned hashed chunks, merging to build final dictionary
    return build_id_hash_map_from_chunks(_hashed_chunks())
