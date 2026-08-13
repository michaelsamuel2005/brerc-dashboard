The reconciliation module ensures that the public dashboard database (occurrence_public) stays precisely synchronised with incoming source data without requiring full table wipes on every run. By leveraging deterministic cryptographic hashing and set-based differential analysis, it identifies new records (inserts), modified rows (updates), and removed observations (deletes) before routing changes securely through the safety pipeline.

File-by-File Breakdown:
hashing.py (Content Hash Generation)
- Computes deterministic SHA-256 hashes (add_content_hash) for every record using a fixed configuration of columns, normalising dates and text to prevent false updates due to minor formatting shifts.

diff.py (Set Differential Analysis)
- Compares source and database hash maps (diff_id_hash_maps) using fast Python set operations to isolate records requiring insertion, updating, or deletion.

streaming.py (Memory-Safe Chunking)
- Streams large source files from disk in configurable blocks (iter_source_chunks) or processes in-memory dataframes, cleaning headers and compiling master source hash maps.

state.py (Database State Retrieval)
- Queries the UI database (get_ui_map) to fetch all existing record IDs and their current content hashes, ensuring type compatibility (str mapping).

map_to_schema.py (Schema Mapping)
- Transforms and formats safe internal dataframe columns into the exact column schema expected by the public-facing occurrence_public table.

reconcile.py (Two-Pass Orchestration)
- Coordinates the overall reconciliation lifecycle (reconcile), handling Pass 1 diffing and Pass 2 chunked processing, safety gate filtering, and persistence dispatch.

The Reconciliation Flow
When a new source dataset is processed, reconciliation executes through a robust, high-performance two-pass architecture:

Pass 1 — Hash Mapping & Diffing (streaming.py, hashing.py, diff.py, db.py):
- The source dataset is streamed in memory-safe chunks, cleaned, and assigned unique SHA-256 content hashes.
- Existing records are fetched from the UI database (get_ui_map).
- Set operations compare source IDs against database IDs to classify changes into inserts (brand-new rows), deletes (missing rows), and possible updates (matching IDs with potentially changed content hashes).

Pass 2 — Processing & Synchronization (pipeline.py, load.py):
- The pipeline streams source chunks a second time, filtering specifically for rows flagged as inserts or updates.
- Identified change chunks are pushed through the complete safety pipeline (make_safe_for_publishing), which strips sensitive data, generalises spatial coordinates, and validates species numbers.
- Safe records are stamped with ETL metadata and written to the database using high-performance staging tables and ON CONFLICT upserts.

Database Purging (load.py):
- Obsolete record IDs identified during Pass 1 deletes are purged from occurrence_public in a single efficient SQL operation (DELETE ... WHERE record_id = ANY(...)).