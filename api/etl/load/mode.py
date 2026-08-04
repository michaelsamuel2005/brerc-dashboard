from etl.load.loader import load_safety_config

CONFIG = load_safety_config()

def should_run_initial_load(
    table_exists: bool,
    table_has_rows: bool,
) -> bool:
    """
    Determines whether the ETL should perform a full initial load.

    Initial load happens when:
    - config explicitly disables incremental mode
    - destination table does not exist
    - destination table exists but is empty
    """

    incremental_enabled = (
        CONFIG["load"]["incremental_check"]
    )

    if not incremental_enabled:
        return True

    if not table_exists:
        return True

    if not table_has_rows:
        return True

    return False