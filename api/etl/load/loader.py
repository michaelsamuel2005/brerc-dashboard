from pathlib import Path
from psycopg2.extras import execute_values

import yaml


DEFAULT_CONFIG_PATH = (
    Path(__file__)
    .resolve()
    .parents[3]
    / "config"
    / "safety.yaml"
)


def load_safety_config(path=None):

    if path is None:
        path = DEFAULT_CONFIG_PATH

    with open(path, "r") as file:
        return yaml.safe_load(file)


def initial_load(df, connection, table_name: str):
    """Full load: wipe the table, insert everything in df."""
    columns = list(df.columns)
    rows = [tuple(row) for row in df.itertuples(index=False)]

    with connection.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {table_name};")
        cols_sql = ", ".join(columns)
        execute_values(
            cur,
            f"INSERT INTO {table_name} ({cols_sql}) VALUES %s",
            rows,
            page_size=10000,
        )
    connection.commit()
    return len(rows)


def incremental_load(df, connection, ui_map, table_name: str):
    """Upsert: insert new rows, update existing ones by primary key."""
    primary_key = ui_map["primary_key"]
    columns = list(df.columns)
    rows = [tuple(row) for row in df.itertuples(index=False)]

    update_cols = [c for c in columns if c != primary_key]
    update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    cols_sql = ", ".join(columns)

    with connection.cursor() as cur:
        execute_values(
            cur,
            f"INSERT INTO {table_name} ({cols_sql}) VALUES %s "
            f"ON CONFLICT ({primary_key}) DO UPDATE SET {update_sql}",
            rows,
            page_size=5000,
        )
    connection.commit()
    return len(rows)