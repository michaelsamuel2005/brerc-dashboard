# pytest etl/tests/profiling/test_record_year.py -v
# (remove -v to see if whole test pass)

import pandas as pd
from etl.profiling.record_year import derive_record_year


def _years(dates, source_years):
    # Builds a fake DF with a free-text date and the source's own year column
    df = pd.DataFrame({"date_of_record": dates, "year_end": source_years})
    return derive_record_year(df, "date_of_record", "year_end").tolist()


def test_readable_date_uses_the_date():
    # A full UK date is read directly, even if the source year disagrees
    assert _years(["14/05/2024"], ["1999"]) == [2024]


def test_junk_before_the_date_is_ignored():
    # BRERC dates sometimes carry a junk prefix; the date inside is still read
    assert _years([" - 17/10/2023"], [None]) == [2023]


def test_vague_month_year_falls_back_to_source_year():
    # "February 2007" can't be read as a date, so the source year is used
    assert _years(["February 2007"], ["2007"]) == [2007]


def test_date_range_uses_source_year_end():
    # For a range BRERC's year is the END year, not the first year in the text
    assert _years(["1985-1990"], ["1990"]) == [1990]


def test_no_date_and_no_source_year_is_missing():
    # Nothing to go on: <NA>, so the caller can skip the record
    result = _years([None], [None])
    assert pd.isna(result[0])


def test_years_are_whole_numbers():
    # Written to the database as 2014, never "2014.0"
    df = pd.DataFrame({"date_of_record": ["01/01/2014", "junk"], "year_end": [None, "2014"]})
    result = derive_record_year(df, "date_of_record", "year_end")
    assert str(result.dtype) == "Int64"


def test_works_without_a_source_year_column():
    # A source with no year column: vague dates are simply missing
    df = pd.DataFrame({"date_of_record": ["14/05/2024", "February 2007"]})
    result = derive_record_year(df, "date_of_record", None)
    assert result.iloc[0] == 2024
    assert pd.isna(result.iloc[1])
