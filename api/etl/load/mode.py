"""
Determines whether the ETL pipeline should perform a full initial load 
or proceed with an incremental load based on configuration and table state.
"""

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()


def should_run_initial_load(
    table_exists: bool,
    table_has_rows: bool,
) -> bool:
    """
    Checks configuration settings and database state to decide 
    if a full initial load is required instead of an incremental update.
    """
    # Check if incremental loading is turned off in the config
    incremental_enabled = CONFIG["load"]["incremental_check"]

    if not incremental_enabled:
        return True

    # If the destination table hasn't been created yet, we must do a full load
    if not table_exists:
        return True

    # If the table exists but is completely empty, we need an initial load
    if not table_has_rows:
        return True

    # Otherwise, it's safe to run an incremental load
    return False
