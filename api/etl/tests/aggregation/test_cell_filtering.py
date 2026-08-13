# pytest etl/tests/aggregation/

import pandas as pd
import pytest

from etl.aggregation.cell_filtering import (
    filter_accepted_records,
)

# --- filter_accepted_records tests ---


def test_filter_accepted_records_keeps_accepted_correct_records():
    # Confirms accepted records are allowed through.
    # Expects one returned record, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "verified": ["Accepted – correct"],
        }
    )

    result = filter_accepted_records(df)

    assert len(result) == 1
    assert result.loc[0, "unique_no"] == 1


def test_filter_accepted_records_keeps_accepted_considered_correct_records():
    # Confirms considered-correct records are allowed through.
    # Expects one returned record, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "verified": ["Accepted – considered correct"],
        }
    )

    result = filter_accepted_records(df)

    assert len(result) == 1


def test_filter_accepted_records_keeps_old_accepted_value():
    # Confirms deprecated "Accepted" values are still supported.
    # Expects one returned record, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "verified": ["Accepted"],
        }
    )

    result = filter_accepted_records(df)

    assert len(result) == 1


def test_filter_accepted_records_marks_missing_verified_as_legacy():
    # Confirms missing verification values are retained as legacy.
    # Expects is_legacy=True, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "verified": [pd.NA],
        }
    )

    result = filter_accepted_records(df)

    assert len(result) == 1
    assert result.loc[0, "is_legacy"]


def test_filter_accepted_records_marks_blank_verified_as_legacy():
    # Confirms blank verification values are retained as legacy.
    # Expects is_legacy=True, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "verified": ["   "],
        }
    )

    result = filter_accepted_records(df)

    assert len(result) == 1
    assert result.loc[0, "is_legacy"]


def test_filter_accepted_records_keeps_brerc_as_legacy():
    # Confirms BRERC legacy records are retained.
    # Expects is_legacy=True, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "verified": ["BRERC"],
        }
    )

    result = filter_accepted_records(df)

    assert len(result) == 1
    assert result.loc[0, "is_legacy"]


def test_filter_accepted_records_removes_unknown_verification_status():
    # Confirms unsupported verification values are removed.
    # Expects empty output, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "verified": ["Rejected"],
        }
    )

    result = filter_accepted_records(df)

    assert len(result) == 0


def test_filter_accepted_records_adds_is_legacy_column():
    # Confirms output includes the legacy flag.
    # Expects is_legacy column, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "verified": ["Accepted – correct"],
        }
    )

    result = filter_accepted_records(df)

    assert "is_legacy" in result.columns


def test_filter_accepted_records_strips_whitespace():
    # Confirms surrounding whitespace does not prevent matching.
    # Expects record retained, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "verified": ["  Accepted – correct  "],
        }
    )

    result = filter_accepted_records(df)

    assert len(result) == 1


def test_filter_accepted_records_preserves_original_columns():
    # Confirms filtering adds the legacy flag without removing source columns.
    # Expects unique_no, scientific_name, and verified columns, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "scientific_name": ["Robin"],
            "verified": ["Accepted – correct"],
        }
    )

    result = filter_accepted_records(df)

    assert "unique_no" in result.columns
    assert "scientific_name" in result.columns
    assert "verified" in result.columns


def test_filter_accepted_records_raises_error_on_missing_verified_column():
    # Confirms a missing verification column correctly halts the function.
    # Expects a KeyError to be raised, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "scientific_name": ["Robin"],
        }
    )

    with pytest.raises(KeyError, match="Missing columns required"):
        filter_accepted_records(df)


def test_filter_accepted_records_normalises_all_dash_types():
    # Confirms standard hyphens and em-dashes are successfully normalised.
    # Expects two retained records with identical evaluation, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1, 2],
            "verified": [
                "Accepted - correct",  # standard hyphen
                "Accepted — correct",  # em-dash
            ],
        }
    )

    result = filter_accepted_records(df)

    assert len(result) == 2
