from datetime import datetime

import pandas as pd

from etl.load.metadata import add_load_metadata


def test_add_load_metadata_adds_columns():
    """
    Confirms ETL load metadata is attached to every row.
    """

    df = pd.DataFrame({
        "id": [1, 2],
    })

    load_number = 5
    load_timestamp = datetime(2026, 8, 4, 12, 30, 0)

    result = add_load_metadata(
        df,
        load_number,
        load_timestamp,
    )

    assert "load_number" in result.columns
    assert "date_of_load" in result.columns

    assert result["load_number"].tolist() == [
        5,
        5,
    ]

    assert result["date_of_load"].tolist() == [
        load_timestamp,
        load_timestamp,
    ]


def test_add_load_metadata_does_not_modify_original_dataframe():
    """
    Confirms the input dataframe is left unchanged.
    """

    df = pd.DataFrame({
        "id": [1],
    })

    add_load_metadata(
        df,
        1,
        datetime.now(),
    )

    assert "load_number" not in df.columns
    assert "date_of_load" not in df.columns


def test_add_load_metadata_preserves_existing_data():
    """
    Confirms existing columns remain unchanged.
    """

    df = pd.DataFrame({
        "id": [1],
        "species": ["Robin"],
    })

    timestamp = datetime(2026, 8, 4)

    result = add_load_metadata(
        df,
        3,
        timestamp,
    )

    assert result["id"].tolist() == [1]
    assert result["species"].tolist() == ["Robin"]