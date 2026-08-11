from pathlib import Path

import psycopg
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

    config_path = Path(path)

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

    with open(config_path, "r") as file:
        return yaml.safe_load(file)
        
def initial_load(df, connection, table_name: str):
    """Full load: wipe the table, insert everything in df."""
    columns = list(df.columns)
    rows = [tuple(row) for row in df.itertuples(index=False)]

    cols_sql = ", ".join(columns)

    with connection.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {table_name};")
        with cur.copy(f"COPY {table_name} ({cols_sql}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
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
    placeholders = ", ".join(["%s"] * len(columns))

    sql = (
        f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({primary_key}) DO UPDATE SET {update_sql}"
    )

    with connection.cursor() as cur:
        cur.executemany(sql, rows)
    connection.commit()
    return len(rows)