import hashlib
import pandas as pd

from etl.reconciliation.hashing import (
    HASH_COLUMNS,
    _normalised_hash_value,
    row_content_hash,
    add_content_hash,
)


# --- _normalised_hash_value tests ---

def test_normalised_hash_value_returns_empty_string_for_missing_value():
    # Confirms missing values are normalised to an empty string.
    # Expects "", else fails.
    assert _normalised_hash_value(pd.NA) == ""


def test_normalised_hash_value_converts_timestamp_to_iso_format():
    # Confirms timestamps are converted to ISO format before hashing.
    # Expects ISO string, else fails.
    timestamp = pd.Timestamp("2024-05-20 14:30:00")

    assert (
        _normalised_hash_value(timestamp)
        == "2024-05-20T14:30:00"
    )


def test_normalised_hash_value_strips_surrounding_whitespace():
    # Confirms leading and trailing whitespace is removed.
    # Expects trimmed string, else fails.
    assert _normalised_hash_value("  Robin  ") == "Robin"


# --- row_content_hash tests ---

def test_row_content_hash_returns_sha256_hex_string():
    # Confirms a SHA-256 hash is produced.
    # Expects a 64-character hexadecimal string, else fails.
    row = pd.Series({
        "scientific_name": "Robin",
        "abundance": "Common",
        "sex_stage": "Adult",
        "record_type": "Observation",
        "vitality": "Alive",
        "verified": "Yes",
        "eastings": 529090,
        "northings": 179645,
    })

    result = row_content_hash(row)

    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_row_content_hash_same_data_produces_same_hash():
    # Confirms identical rows always produce identical hashes.
    # Expects matching hashes, else fails.
    row = pd.Series({
        "scientific_name": "Robin",
        "abundance": "Common",
        "sex_stage": "Adult",
        "record_type": "Observation",
        "vitality": "Alive",
        "verified": "Yes",
        "eastings": 529090,
        "northings": 179645,
    })

    assert row_content_hash(row) == row_content_hash(row)


def test_row_content_hash_detects_changed_value():
    # Confirms changing one hashed field changes the hash.
    # Expects different hashes, else fails.
    row1 = pd.Series({
        "scientific_name": "Robin",
        "abundance": "Common",
        "sex_stage": "Adult",
        "record_type": "Observation",
        "vitality": "Alive",
        "verified": "Yes",
        "eastings": 529090,
        "northings": 179645,
    })

    row2 = row1.copy()
    row2["verified"] = "No"

    assert row_content_hash(row1) != row_content_hash(row2)


# --- add_content_hash tests ---

def test_add_content_hash_adds_content_hash_column():
    # Confirms the function creates a content_hash column.
    # Expects the column to exist, else fails.
    df = pd.DataFrame({
        "scientific_name": ["Robin"],
        "abundance": ["Common"],
        "sex_stage": ["Adult"],
        "record_type": ["Observation"],
        "vitality": ["Alive"],
        "verified": ["Yes"],
        "eastings": [529090],
        "northings": [179645],
    })

    result = add_content_hash(df)

    assert "content_hash" in result.columns


def test_add_content_hash_returns_one_hash_per_row():
    # Confirms every input row receives a content hash.
    # Expects the number of hashes to equal the number of rows.
    df = pd.DataFrame({
        "scientific_name": ["Robin", "Blackbird"],
        "abundance": ["Common", "Common"],
        "sex_stage": ["Adult", "Adult"],
        "record_type": ["Observation", "Observation"],
        "vitality": ["Alive", "Alive"],
        "verified": ["Yes", "Yes"],
        "eastings": [529090, 529100],
        "northings": [179645, 179650],
    })

    result = add_content_hash(df)

    assert len(result["content_hash"]) == 2
    assert result["content_hash"].notna().all()


def test_add_content_hash_preserves_existing_columns():
    # Confirms existing data columns are preserved.
    # Expects all original columns plus content_hash.
    df = pd.DataFrame({
        "scientific_name": ["Robin"],
        "abundance": ["Common"],
        "sex_stage": ["Adult"],
        "record_type": ["Observation"],
        "vitality": ["Alive"],
        "verified": ["Yes"],
        "eastings": [529090],
        "northings": [179645],
        "unique_no": [123],
    })

    result = add_content_hash(df)

    assert "unique_no" in result.columns
    assert result.loc[0, "unique_no"] == 123
    assert "content_hash" in result.columns