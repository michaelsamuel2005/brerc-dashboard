# pytest etl/tests/profiling/test_cleaning.py -v 
# (remove -v to see if whole test pass)

import pandas as pd
from etl.profiling.cleaning import clean_data

def test_clean_data_lowercases_column_names():
    # Builds fake DF - Column with mixed-case name
    # Checks if column name xomes out lowercase, else fails
    df = pd.DataFrame({"Scientific_Name": ["Vulpes vulpes"]})
    result = clean_data(df)
    assert "scientific_name" in result.columns


def test_clean_data_strips_and_replaces_spaces_in_column_names():
    # Builds column name with trailing/leading spaces
    # Expects: no leading/trailing spaces, else fails
    df = pd.DataFrame({" Record Type ": ["sighting"]})
    result = clean_data(df)
    assert "record_type" in result.columns


def test_clean_data_does_not_change_row_values():
    # checks if clean_data only touches the column names, not data
    # Values should remain untouched
    df = pd.DataFrame({"Species_No": [123, 456]})
    result = clean_data(df)
    assert result["species_no"].tolist() == [123, 456]


def test_clean_data_does_not_change_row_count():
    # Confirms clean_data never drops or add rows
    # Expects all rows to remain, else fails
    df = pd.DataFrame({"Species_No": [1, 2, 3]})
    result = clean_data(df)
    assert len(result) == 3