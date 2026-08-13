The etl/load module handles pushing processed data frames safely into PostgreSQL. It intelligently decides whether to perform a full wipe-and-reload or an incremental upsert, manages audit metadata, and handles high-privilege schema operations.

File-by-File Breakdown
loader.py (Core Database Loader & Config)
- Loads YAML configuration settings (safety.yaml) and executes the actual SQL operations: bulk inserts using PostgreSQL's fast COPY command for initial loads, and ON CONFLICT upserts for incremental loads.

mode.py (Decision Logic)
- Evaluates configuration flags and table states to determine whether the pipeline must run a full initial load (should_run_initial_load).

metadata.py (Audit Tracking & Watermarks)
- Attaches ETL run metadata (Load mode and Load_date timestamps) to every row and queries the database for the latest watermark (get_last_load_date).

reload.py (Schema Rebuilds & DDL Operations)
- Manages privileged database operations (like dropping and recreating the entire schema via b6_schema.sql) using isolated admin credentials, keeping DDL actions completely separate from standard loading.

runner.py (Orchestration Coordinator)
- Inspects the destination table's existence and row counts (_get_destination_table_status), then coordinates and dispatches the data to the correct loading strategy (run_load).

When a dataset is ready to be written to the database, the process moves through a structured pipeline:

1. Table Status Check (run.py):
- The pipeline inspects the destination table in PostgreSQL to see if it exists and whether it contains any rows.

2. Decision Making (mode.py):
- It checks safety.yaml and the table status. If incremental loading is disabled, or if the table is missing or empty, it flags the run for an initial load. Otherwise, it opts for an incremental load.

3. Metadata Stamping (metadata.py):
- Audit columns (Load and Load_date) are stamped onto every row in the dataframe so every record tracks which ETL run produced it.

4. Execution (loader.py):
- Initial Load Route: Truncates the table clean and bulk-loads everything using PostgreSQL's high-speed COPY command.

- Incremental Load Route: Executes an upsert (INSERT ... ON CONFLICT DO UPDATE), inserting brand-new records and refreshing existing ones based on primary keys.

5. Admin Reset (Fallback/Ops):
- If a full structural database reset is required due to corruption or schema changes, admin.py handles executing the core b6_schema.sql script with isolated admin privileges.