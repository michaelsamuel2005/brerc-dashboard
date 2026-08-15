The etl/load module handles the config, decision-making, and audit metadata around getting data into PostgreSQL — deciding whether a run needs a full wipe-and-reload or an incremental upsert, stamping audit columns, and handling the high-privilege schema rebuild. It does not do the actual row-by-row writing itself; that happens in etl/reconciliation/load.py and etl/aggregation/persist.py.

File-by-File Breakdown

loader.py (Config)
- Loads YAML configuration settings (safety.yaml).

mode.py (Decision Logic)
- Evaluates configuration flags and table states to determine whether the pipeline must run a full initial load (should_run_initial_load).

metadata.py (Audit Tracking & Watermarks)
- Attaches ETL run metadata (Load mode and Load_date timestamps) to every row and queries the database for the latest watermark (get_last_load_date).

reload.py (Schema Rebuilds & DDL Operations)
- Manages privileged database operations (dropping and recreating the entire schema via b6_schema.sql) using isolated admin credentials, keeping DDL actions completely separate from standard loading.

When a dataset is ready to be written to the database, the process moves through a structured pipeline (see etl/job.py):

1. Table Status Check (etl/db.py):
- The pipeline inspects the destination table in PostgreSQL to see if it exists and whether it contains any rows.

2. Decision Making (mode.py):
- It checks safety.yaml and the table status. If incremental loading is disabled, or if the table is missing or empty, it flags the run for an initial load. Otherwise, it opts for an incremental load.

3. Schema Reset, if initial (reload.py):
- force_full_reload() drops and recreates the schema from b6_schema.sql using isolated admin credentials, so the run starts from a clean slate.

4. Metadata Stamping (metadata.py):
- Audit columns (Load and Load_date) are stamped onto every row in the dataframe so every record tracks which ETL run produced it.

5. Execution (etl/reconciliation/load.py + etl/aggregation/persist.py):
- Reconciliation diffs source vs. what's already in the table and inserts, updates, or deletes occurrence records accordingly. Aggregation separately upserts the species index and rebuilds distribution_cell.
