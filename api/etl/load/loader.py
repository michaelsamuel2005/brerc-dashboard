"""
Loads configuration settings from YAML files and handles 
initial (full wipe) and incremental (upsert) database loading.
"""

from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "safety.yaml"


def load_safety_config(path=None):
    """Loads the safety configuration YAML file, falling back to an example file if needed."""
    if path is None:
        config_path = DEFAULT_CONFIG_PATH

        # Fall back to the example config if the real one isn't present
        if not config_path.exists():
            example_path = config_path.with_suffix(config_path.suffix + ".example")

            if example_path.exists():
                config_path = example_path
            else:
                raise FileNotFoundError(
                    f"Neither configuration file {config_path} "
                    f"nor fallback {example_path} could be found."
                )
    else:
        config_path = path

    with open(config_path, "r") as file:
        return yaml.safe_load(file)


def initial_load(df, connection, table_name: str):
    """Performs a full load by wiping the table completely and bulk-inserting all rows."""
    columns = list(df.columns)
    rows = [tuple(row) for row in df.itertuples(index=False)]

    cols_sql = ", ".join(columns)

    with connection.cursor() as cur:
        # Wipes the table clean for a fresh start
        cur.execute(f"TRUNCATE TABLE {table_name};")

        # Use PostgreSQL's fast copy command to insert everything at once
        with cur.copy(f"COPY {table_name} ({cols_sql}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)

    connection.commit()
    return len(rows)


def incremental_load(df, connection, ui_map, table_name: str):
    """Performs an upsert: inserts new rows or updates existing ones based on primary keys."""
    primary_key = ui_map["primary_key"]
    columns = list(df.columns)
    rows = [tuple(row) for row in df.itertuples(index=False)]

    # Update all columns except the primary key itself
    update_cols = [c for c in columns if c != primary_key]
    cols_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))

    if update_cols:
        update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

        conflict_sql = f"ON CONFLICT ({primary_key}) DO UPDATE SET {update_sql}"
    else:
        conflict_sql = f"ON CONFLICT ({primary_key}) DO NOTHING"

    sql = (
        f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders}) "
        f"{conflict_sql}"
    )

    with connection.cursor() as cur:
        # Push rows in bulk, letting PostgreSQL handle conflicts automatically
        cur.executemany(sql, rows)

    connection.commit()
    return len(rows)
