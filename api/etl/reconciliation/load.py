import pandas as pd


def insert_records(
    records_df: pd.DataFrame,
    connection,
) -> None:
    """
    Insert new records into the UI database.
    """

    if records_df.empty:
        return

    # TODO:
    # INSERT SQL once the final database schema is merged.
    pass


def update_records(
    records_df: pd.DataFrame,
    connection,
) -> None:
    """
    Update existing records whose source content has changed.
    """

    if records_df.empty:
        return

    # TODO:
    # UPDATE SQL once the final database schema is merged.
    pass


def delete_records(
    record_ids: set,
    connection,
) -> None:
    """
    Delete records no longer present in the source data.
    """

    if not record_ids:
        return

    # TODO:
    # DELETE SQL once the final database schema is merged.
    pass