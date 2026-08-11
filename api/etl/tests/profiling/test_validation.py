import pandas as pd
from etl.profiling.validation import (
    validate_unique_no,
    validate_species_name,
    validate_avon_flag,
    validate_record_type,
    calculate_dictionary_match,
    get_sensitive_record_types,
    get_verified_types,
)

# --- Mock data, defined once, reused by tests below ---

UNIQUE_NO_SAMPLE = pd.DataFrame(
    {"unique_no": [1, 1, 2, None]}  # 1 duplicate, 1 missing, 2 unique
)

SPECIES_NAME_SAMPLE = pd.DataFrame(
    {
        "scientific_name": [
            "Vulpes vulpes",
            "notvalidname",
            None,
        ]  # 1 valid, 1 invalid, 1 missing
    }
)

AVON_FLAG_SAMPLE = pd.DataFrame(
    {"outofavon": ["Yes", "No", "Maybe", None]}  # 2 valid, 1 invalid, 1 missing
)

DICTIONARY_MATCH_RECORDS = pd.DataFrame(
    {"scientific_name": ["Vulpes vulpes", "Meles meles", "Unknown sp"]}
)
DICTIONARY_MATCH_DICTIONARY = pd.DataFrame(
    {"scientific": ["Vulpes vulpes", "Meles meles"]}  # 2 of 3 records match
)

SENSITIVE_RECORD_TYPE_SAMPLE = pd.DataFrame(
    {
        "recordtype": ["roost", "sighting", "roost"],
        "sensitive": ["yes", "no", "yes"],  # only "roost" is sensitive
    }
)

RECORD_TYPE_SAMPLE = pd.DataFrame(
    {
        "record_type": [
            "sighting",
            "roost",
            "sighting",
            None,
        ]  # 2 distinct values, 1 missing
    }
)

VERIFIED_TYPE_SAMPLE = pd.DataFrame(
    {"verified": ["Accepted", "Accepted", None]}  # 1 distinct value, 1 missing
)


# --- Tests ---


def test_validate_unique_no_reports_missing_column(capsys):
    # Confirms validate_unique_no handles a dataframe with no unique_no column.
    # Expects a "column does not exist" message, else fails.
    df = pd.DataFrame({"other_column": [1, 2, 3]})
    validate_unique_no(df)
    captured = capsys.readouterr()
    assert "unique_no column does not exist" in captured.out


def test_validate_unique_no_detects_duplicates_and_missing(capsys):
    # Confirms validate_unique_no correctly counts duplicate and missing values.
    # Expects 1 duplicate, 1 missing, 2 unique — matching UNIQUE_NO_SAMPLE, else fails.
    validate_unique_no(UNIQUE_NO_SAMPLE)
    captured = capsys.readouterr()
    assert "Duplicate values: 1" in captured.out
    assert "Missing values: 1" in captured.out
    assert "Unique values: 2" in captured.out


def test_validate_species_name_flags_invalid_format(capsys):
    # Confirms validate_species_name flags names that don't match the
    # "Genus species" pattern, and counts missing names separately.
    # Expects 1 missing name reported and an invalid-names section, else fails.
    validate_species_name(SPECIES_NAME_SAMPLE)
    captured = capsys.readouterr()
    assert "Missing species names: 1" in captured.out
    assert "Potentially invalid names:" in captured.out


def test_validate_avon_flag_detects_invalid_values(capsys):
    # Confirms validate_avon_flag only accepts "Yes"/"No" as valid values.
    # Expects "Maybe" and the missing value to count as invalid (2), else fails.
    validate_avon_flag(AVON_FLAG_SAMPLE)
    captured = capsys.readouterr()
    assert "Invalid values: 2" in captured.out  # "Maybe" + None
    assert "Valid values: 2" in captured.out


def test_validate_record_type_reports_missing_column(capsys):
    # Confirms validate_record_type handles a dataframe with no record_type column.
    # Expects a "column does not exist" message, else fails.
    df = pd.DataFrame({"other_column": [1]})
    validate_record_type(df)
    captured = capsys.readouterr()
    assert "record_type column does not exist" in captured.out


def test_validate_record_type_reports_distinct_values_and_missing(capsys):
    # Confirms validate_record_type reports distinct values and missing count
    # when the column exists and has real data.
    # Expects 1 missing value reported, else fails.
    validate_record_type(RECORD_TYPE_SAMPLE)
    captured = capsys.readouterr()
    assert "Missing values" in captured.out
    assert "1" in captured.out


def test_calculate_dictionary_match_computes_match_rate(capsys):
    # Confirms calculate_dictionary_match correctly counts matched vs
    # unmatched species names between records and the dictionary.
    # Expects 3 distinct records, 2 matched, 1 unmatched, else fails.
    calculate_dictionary_match(DICTIONARY_MATCH_RECORDS, DICTIONARY_MATCH_DICTIONARY)
    captured = capsys.readouterr()
    assert "Distinct record names: 3" in captured.out
    assert "Matched names: 2" in captured.out
    assert "Unmatched names: 1" in captured.out


def test_get_sensitive_record_types_filters_correctly(capsys):
    # Confirms get_sensitive_record_types only returns record types
    # where sensitive == "yes", and counts distinct types only.
    # Expects 1 distinct sensitive type ("roost"), else fails.
    get_sensitive_record_types(SENSITIVE_RECORD_TYPE_SAMPLE)
    captured = capsys.readouterr()
    assert "Distinct record names: 1" in captured.out  # only "roost"


def test_get_verified_types_reports_missing_column(capsys):
    # Confirms get_verified_types handles a dataframe with no verified column.
    # Expects a "column does not exist" message, else fails.
    df = pd.DataFrame({"other_column": [1]})
    get_verified_types(df)
    captured = capsys.readouterr()
    assert "verified column does not exist" in captured.out


def test_get_verified_types_reports_distinct_values_and_missing(capsys):
    # Confirms get_verified_types reports distinct values and missing count
    # when the column exists and has real data.
    # Expects 1 missing value reported, else fails.
    get_verified_types(VERIFIED_TYPE_SAMPLE)
    captured = capsys.readouterr()
    assert "Missing values" in captured.out
    assert "1" in captured.out
