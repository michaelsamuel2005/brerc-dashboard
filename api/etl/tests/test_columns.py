# pytest etl/tests/test_columns.py -v
# (remove -v to see if whole test pass)

from unittest.mock import patch

import pandas as pd
import pytest

from etl.columns import ColumnMappingError, has_role, source_column, to_pipeline_names

# A safety.yaml 'columns:' section where BRERC's names differ from the pipeline's
FAKE_CONFIG = {
    "columns": {
        "unique_no": "unique_no",
        "modified_date": "datemdbmodified",
        "source_year": None,  # null: this source has no such column
    }
}


def _translate(df, required=("unique_no", "modified_date")):
    with patch.dict("etl.columns.CONFIG", FAKE_CONFIG, clear=True):
        return to_pipeline_names(df, "columns", required=required, what="the test data")


def test_renames_brerc_columns_to_pipeline_names():
    # BRERC's "datemdbmodified" comes out as the pipeline's "modified_date"
    df = pd.DataFrame({"unique_no": [1], "datemdbmodified": ["2026-01-01"]})
    result = _translate(df)
    assert list(result.columns) == ["unique_no", "modified_date"]
    assert result["modified_date"].tolist() == ["2026-01-01"]


def test_drops_every_column_that_is_not_mapped():
    # Place and comments are not in safety.yaml, so they never enter the pipeline
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "datemdbmodified": ["2026-01-01"],
            "place": ["Secret Wood"],
            "comments": ["badger sett by the stile"],
        }
    )
    result = _translate(df)
    assert "place" not in result.columns
    assert "comments" not in result.columns


def test_a_mapped_column_missing_from_the_data_stops_the_run():
    # BRERC renamed a column: the error names the safety.yaml line to fix
    df = pd.DataFrame({"unique_no": [1], "date_modified": ["2026-01-01"]})
    with pytest.raises(ColumnMappingError) as raised:
        _translate(df)
    assert "'columns: modified_date' is 'datemdbmodified'" in str(raised.value)


def test_a_required_role_that_is_not_mapped_stops_the_run():
    # safety.yaml forgot a column the pipeline cannot work without
    df = pd.DataFrame({"unique_no": [1], "datemdbmodified": ["2026-01-01"]})
    with pytest.raises(ColumnMappingError) as raised:
        _translate(df, required=("unique_no", "modified_date", "verified"))
    assert "verified" in str(raised.value)


def test_null_mapping_means_the_source_does_not_have_it():
    # source_year: null is optional and absent, not an error
    with patch.dict("etl.columns.CONFIG", FAKE_CONFIG, clear=True):
        assert has_role("modified_date")
        assert not has_role("source_year")


def test_source_column_gives_brercs_name_for_a_role():
    # Used by the incremental SQL filter, which runs before translation
    with patch.dict("etl.columns.CONFIG", FAKE_CONFIG, clear=True):
        assert source_column("modified_date") == "datemdbmodified"
